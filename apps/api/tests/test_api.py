import asyncio
import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["APP_ENV"] = "test"
os.environ["DEEPSEEK_API_KEY"] = ""
API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.api.deps import get_deepagents_service, get_service
from app.core.schemas import ConfirmStepRequest, DraftArtifact, ModeUpdateRequest, RegenerateRequest, ReviewBatch, ReviewSubmitRequest, ReviewCriterionResult
from app.core.settings import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def isolate_test_state(tmp_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    get_settings.cache_clear()
    get_service.cache_clear()
    get_deepagents_service.cache_clear()
    yield
    get_settings.cache_clear()
    get_service.cache_clear()
    get_deepagents_service.cache_clear()


@pytest.mark.asyncio
async def test_thread_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/threads")
        assert created.status_code == 200
        thread_id = created.json()["data"]["thread"]["thread_id"]

        listed = await client.get("/api/v1/threads")
        assert listed.status_code == 200
        matching = next(item for item in listed.json()["data"]["threads"] if item["thread_id"] == thread_id)
        assert matching["title"]
        assert matching["subtitle"] in {"继续对话", "继续补充需求"}

        sent = await client.post(
            f"/api/v1/threads/{thread_id}/messages",
            json={"content": "我要做一节面向初中生的数学课，先聚焦初二三角函数。"},
        )
        assert sent.status_code == 200

        thread = await client.get(f"/api/v1/threads/{thread_id}")
        payload = thread.json()["data"]["state"]
        assert payload["draft_artifact"] is None
        assert payload["messages"][-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_thread_generation_persists_artifact_and_review_batch():
    service = get_service()
    thread = await service.create_thread()
    await service.ingest_message(
        thread.thread_id,
        "我要做一门入门课，给初中生，主题是三角函数，解决基础题不会做的问题，学完能独立完成基础题，风格实操带练，时长90分钟，要求基于真实案例。",
        "default-user",
    )
    await service.ingest_message(thread.thread_id, "开始生成", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    assert state.draft_artifact is not None
    assert state.review_batches
    assert state.review_batches[-1].total_score >= 0


@pytest.mark.asyncio
async def test_low_score_triggers_auto_optimization_loop(monkeypatch: pytest.MonkeyPatch):
    get_service.cache_clear()
    service = get_service()
    calls = {"review": 0, "improve": 0}

    async def fake_review_markdown(*, markdown: str, rubric: list[dict], threshold: float):
        calls["review"] += 1
        if calls["review"] == 1:
            return {
                "total_score": 6.5,
                "criteria": [
                    {
                        "criterion_id": item["criterion_id"],
                        "name": item["name"],
                        "weight": item["weight"],
                        "score": 6.0,
                        "max_score": item["max_score"],
                        "reason": "需要优化。",
                    }
                    for item in rubric
                ],
                "suggestions": [
                    {
                        "criterion_id": "script-quality",
                        "problem": "逐字稿过于空泛。",
                        "suggestion": "把案例 2 和案例 3 的讲解扩写成可直接授课的口语化表达。",
                        "evidence_span": "逐字稿",
                        "severity": "high",
                    }
                ],
            }
        return {
            "total_score": 8.6,
            "criteria": [
                {
                    "criterion_id": item["criterion_id"],
                    "name": item["name"],
                    "weight": item["weight"],
                    "score": 8.6,
                    "max_score": item["max_score"],
                    "reason": "已达标。",
                }
                for item in rubric
            ],
            "suggestions": [],
        }

    async def fake_improve_markdown(**kwargs):
        calls["improve"] += 1
        return kwargs["markdown"] + "\n\n## 自动优化说明\n\n已根据评分建议补强逐字稿。"

    monkeypatch.setattr(service.graph.deepseek, "review_markdown", fake_review_markdown)
    monkeypatch.setattr(service.graph.deepseek, "improve_markdown", fake_improve_markdown)

    thread = await service.create_thread()
    await service.ingest_message(
        thread.thread_id,
        "我要做一门入门课，给初中生，主题是三角函数，解决基础题不会做的问题，学完能独立完成基础题，风格实操带练，时长90分钟，要求基于真实案例。",
        "default-user",
    )
    await service.ingest_message(thread.thread_id, "开始生成", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    assert calls["review"] >= 2
    assert calls["improve"] == 1
    assert state.runtime.generation_session is not None
    assert state.runtime.generation_session.auto_optimization_loops == 1
    assert state.review_batches[-1].total_score == 8.6


@pytest.mark.asyncio
async def test_timeline_versions_and_regenerate_endpoint(monkeypatch: pytest.MonkeyPatch):
    service = get_service()

    async def fake_improve_markdown(**kwargs):
        assert "不要咖啡馆案例" in kwargs["constraint_summary"]
        return kwargs["markdown"] + "\n\n## 修订说明\n\n已替换为办公场景案例。"

    async def fake_review_markdown(*, markdown: str, rubric: list[dict], threshold: float):
        return {
            "total_score": 8.6,
            "criteria": [
                {
                    "criterion_id": item["criterion_id"],
                    "name": item["name"],
                    "weight": item["weight"],
                    "score": 8.6,
                    "max_score": item["max_score"],
                    "reason": "已达标。",
                }
                for item in rubric
            ],
            "suggestions": [],
        }

    monkeypatch.setattr(service.graph.deepseek, "improve_markdown", fake_improve_markdown)
    monkeypatch.setattr(service.graph.deepseek, "review_markdown", fake_review_markdown)

    thread = await service.create_thread()
    await service.ingest_message(
        thread.thread_id,
        "我要做一门入门课，给初中生，主题是三角函数，解决基础题不会做的问题，学完能独立完成基础题，风格实操带练，时长90分钟，要求基于真实案例。",
        "default-user",
    )
    await service.ingest_message(thread.thread_id, "开始生成", "default-user")

    state = await service.store.get_thread(thread.thread_id)
    base_version = state.draft_artifact.version

    await service.ingest_message(thread.thread_id, "不要咖啡馆案例", "default-user")
    artifact = await service.regenerate(
        thread.thread_id,
        request=RegenerateRequest(instruction="不要咖啡馆案例，换成办公场景案例", base_version=base_version),
    )

    assert artifact.version >= base_version + 1
    assert artifact.source_version == base_version
    assert "咖啡馆" not in artifact.markdown

    timeline = await service.get_timeline(thread.thread_id)
    event_types = [item.event_type for item in timeline]
    assert "generation_started" in event_types
    assert "revision_completed" in event_types

    versions = await service.list_versions(thread.thread_id)
    assert len(versions) >= 2


@pytest.mark.asyncio
async def test_new_api_endpoints_and_deepagents_experiment():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/threads")
        thread_id = created.json()["data"]["thread"]["thread_id"]

        await client.post(
            f"/api/v1/threads/{thread_id}/messages",
            json={"content": "我要做一节 AI 入门课，主题是提示词，目标是完成日报，时长 60 分钟。"},
        )

        timeline = await client.get(f"/api/v1/threads/{thread_id}/timeline")
        assert timeline.status_code == 200
        assert "timeline" in timeline.json()["data"]

        versions = await client.get(f"/api/v1/threads/{thread_id}/versions")
        assert versions.status_code == 200

        bundle = await client.post(
            "/api/v1/experiments/deepagents/plan",
            json={"thread_id": thread_id, "prompt": "先给我复杂规划建议", "include_thread_context": True},
        )
        assert bundle.status_code == 200
        assert bundle.json()["data"]["bundle"]["summary"]


@pytest.mark.asyncio
async def test_pause_and_delete_thread_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/threads")
        thread_id = created.json()["data"]["thread"]["thread_id"]

        paused = await client.post(f"/api/v1/threads/{thread_id}/pause")
        assert paused.status_code == 200

        thread = await client.get(f"/api/v1/threads/{thread_id}")
        assert thread.json()["data"]["state"]["status"] == "paused"

        resumed = await client.post(f"/api/v1/threads/{thread_id}/resume")
        assert resumed.status_code == 200

        deleted = await client.delete(f"/api/v1/threads/{thread_id}")
        assert deleted.status_code == 200

        missing = await client.get(f"/api/v1/threads/{thread_id}")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_pause_cancels_active_generation(monkeypatch: pytest.MonkeyPatch):
    service = get_service()
    service.settings.app_env = "development"
    cancelled = {"value": False}

    async def fake_run_thread(thread_id: str):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled["value"] = True
            raise

    monkeypatch.setattr(service.graph, "run_thread", fake_run_thread)

    thread = await service.create_thread()
    await service.ingest_message(thread.thread_id, "我要做一节数学课", "default-user")
    await asyncio.sleep(0.1)
    await service.pause_thread(thread.thread_id)

    state = await service.store.get_thread(thread.thread_id)
    assert cancelled["value"] is True
    assert state.status.value == "paused"


@pytest.mark.asyncio
async def test_mode_switch_and_step_confirmation_persist_artifact(tmp_path: Path):
    service = get_service()
    thread = await service.create_thread()

    updated = await service.update_mode(thread.thread_id, request=ModeUpdateRequest(mode="series"))
    assert updated.course_mode.value == "series"
    assert updated.current_step_id == "series_framework"
    assert [step.step_id for step in updated.workflow_steps] == ["series_framework"]

    state = await service.store.get_thread(thread.thread_id)
    state.draft_artifact = DraftArtifact(
        version=1,
        markdown="# 系列课程框架\n\n内容",
        summary="系列框架",
    )
    state.review_batches.append(
        ReviewBatch(
            step_id="series_framework",
            draft_version=1,
            total_score=8.8,
            threshold=8.0,
            criteria=[
                ReviewCriterionResult(
                    criterion_id="core-problem",
                    name="核心问题",
                    weight=1.0,
                    score=8.8,
                    max_score=10,
                    reason="达标",
                )
            ],
            suggestions=[],
        )
    )
    await service.store.save_thread(state)

    confirmed = await service.confirm_step(thread.thread_id, request=ConfirmStepRequest(step_id="series_framework"))
    assert confirmed.workflow_steps[0].status.value == "completed"
    assert confirmed.status.value == "completed"
    assert any(item.filename == "series_framework.md" for item in confirmed.saved_artifacts)


@pytest.mark.asyncio
async def test_completion_gate_all_rejected_but_score_passes(monkeypatch: pytest.MonkeyPatch):
    get_service.cache_clear()
    service = get_service()

    async def fake_review_markdown(*, markdown: str, rubric: list[dict], threshold: float):
        return {
            "total_score": 8.8,
            "criteria": [
                {
                    "criterion_id": item["criterion_id"],
                    "name": item["name"],
                    "weight": item["weight"],
                    "score": 8.8,
                    "max_score": item["max_score"],
                    "reason": "整体达标。",
                }
                for item in rubric
            ],
            "suggestions": [
                {
                    "criterion_id": "case-design",
                    "problem": "案例可以更贴近课堂。",
                    "suggestion": "把示例替换成更贴近课堂的场景。",
                    "evidence_span": "案例部分",
                    "severity": "medium",
                }
            ],
        }

    monkeypatch.setattr(service.graph.deepseek, "review_markdown", fake_review_markdown)

    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, request=ModeUpdateRequest(mode="series"))
    await service.ingest_message(
        thread.thread_id,
        "我要做一门入门课，给初中生，解决三角函数基础题不会做的问题，学完能独立完成基础题，风格实操带练，要求基于真实案例。",
        "default-user",
    )
    await service.ingest_message(thread.thread_id, "开始生成", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    batch = state.review_batches[-1]

    await service.submit_review(
        thread.thread_id,
        batch.review_batch_id,
        ReviewSubmitRequest(
            review_actions=[
                {
                    "suggestion_id": batch.suggestions[0].suggestion_id,
                    "action": "reject",
                }
            ]
        ),
    )

    state = await service.store.get_thread(thread.thread_id)
    assert state.status == "review_pending"

    confirmed = await service.confirm_step(thread.thread_id, ConfirmStepRequest(step_id="series_framework"))
    assert confirmed.status.value == "completed"


@pytest.mark.asyncio
async def test_interrupt_resume_survives_service_restart(monkeypatch: pytest.MonkeyPatch):
    get_service.cache_clear()
    service = get_service()

    async def fake_review_markdown(*, markdown: str, rubric: list[dict], threshold: float):
        return {
            "total_score": 8.5,
            "criteria": [
                {
                    "criterion_id": item["criterion_id"],
                    "name": item["name"],
                    "weight": item["weight"],
                    "score": 8.5,
                    "max_score": item["max_score"],
                    "reason": "整体达标。",
                }
                for item in rubric
            ],
            "suggestions": [
                {
                    "criterion_id": "script-quality",
                    "problem": "逐字稿还能再自然一点。",
                    "suggestion": "让结尾部分更口语化。",
                    "evidence_span": "结尾",
                    "severity": "low",
                }
            ],
        }

    monkeypatch.setattr(service.graph.deepseek, "review_markdown", fake_review_markdown)

    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, request=ModeUpdateRequest(mode="series"))
    await service.ingest_message(
        thread.thread_id,
        "我要做一门入门课，给初中生，解决三角函数基础题不会做的问题，学完能独立完成基础题，风格实操带练，要求基于真实案例。",
        "default-user",
    )
    await service.ingest_message(thread.thread_id, "开始生成", "default-user")

    original_state = await service.store.get_thread(thread.thread_id)
    batch = original_state.review_batches[-1]

    get_service.cache_clear()
    restarted = get_service()
    monkeypatch.setattr(restarted.graph.deepseek, "review_markdown", fake_review_markdown)

    await restarted.submit_review(
        thread.thread_id,
        batch.review_batch_id,
        ReviewSubmitRequest(
            review_actions=[
                {
                    "suggestion_id": batch.suggestions[0].suggestion_id,
                    "action": "reject",
                }
            ]
        ),
    )

    resumed_state = await restarted.store.get_thread(thread.thread_id)
    assert resumed_state.status == "review_pending"

    confirmed = await restarted.confirm_step(thread.thread_id, ConfirmStepRequest(step_id="series_framework"))
    assert confirmed.status.value == "completed"


@pytest.mark.asyncio
async def test_auto_optimization_loops_do_not_leak_into_regenerate(monkeypatch: pytest.MonkeyPatch):
    get_service.cache_clear()
    service = get_service()
    calls = {"review": 0}

    async def fake_review_markdown(*, markdown: str, rubric: list[dict], threshold: float):
        calls["review"] += 1
        if calls["review"] == 1:
            return {
                "total_score": 6.5,
                "criteria": [
                    {
                        "criterion_id": item["criterion_id"],
                        "name": item["name"],
                        "weight": item["weight"],
                        "score": 6.0,
                        "max_score": item["max_score"],
                        "reason": "需要优化。",
                    }
                    for item in rubric
                ],
                "suggestions": [
                    {
                        "criterion_id": "script-quality",
                        "problem": "逐字稿过于空泛。",
                        "suggestion": "补强案例讲解。",
                        "evidence_span": "逐字稿",
                        "severity": "high",
                    }
                ],
            }
        return {
            "total_score": 8.9,
            "criteria": [
                {
                    "criterion_id": item["criterion_id"],
                    "name": item["name"],
                    "weight": item["weight"],
                    "score": 8.9,
                    "max_score": item["max_score"],
                    "reason": "已达标。",
                }
                for item in rubric
            ],
            "suggestions": [],
        }

    async def fake_improve_markdown(**kwargs):
        return kwargs["markdown"] + "\n\n## 补强\n\n已补强案例。"

    monkeypatch.setattr(service.graph.deepseek, "review_markdown", fake_review_markdown)
    monkeypatch.setattr(service.graph.deepseek, "improve_markdown", fake_improve_markdown)

    thread = await service.create_thread()
    await service.ingest_message(
        thread.thread_id,
        "我要做一门入门课，给初中生，主题是三角函数，解决基础题不会做的问题，学完能独立完成基础题，风格实操带练，时长 60 分钟，要求基于真实案例。",
        "default-user",
    )
    await service.ingest_message(thread.thread_id, "开始生成", "default-user")

    state = await service.store.get_thread(thread.thread_id)
    base_version = state.draft_artifact.version
    assert state.runtime.generation_session is not None
    assert state.runtime.generation_session.auto_optimization_loops == 1

    await service.regenerate(
        thread.thread_id,
        RegenerateRequest(instruction="换成新的课堂案例", base_version=base_version),
    )

    state = await service.store.get_thread(thread.thread_id)
    assert state.runtime.generation_session is None or state.runtime.generation_session.auto_optimization_loops == 0


@pytest.mark.asyncio
async def test_mode_specific_steps_are_distinct():
    service = get_service()
    thread = await service.create_thread()
    state = await service.store.get_thread(thread.thread_id)
    assert [step.step_id for step in state.workflow_steps] == [
        "course_title",
        "course_framework",
        "case_output",
        "script_output",
        "material_checklist",
    ]

    updated = await service.update_mode(thread.thread_id, ModeUpdateRequest(mode="series"))
    assert [step.step_id for step in updated.workflow_steps] == ["series_framework"]


@pytest.mark.asyncio
async def test_confirm_step_rejects_when_artifact_or_review_missing():
    service = get_service()
    thread = await service.create_thread()

    with pytest.raises(ValueError):
        await service.confirm_step(thread.thread_id, ConfirmStepRequest(step_id="course_title"))

    state = await service.store.get_thread(thread.thread_id)
    state.draft_artifact = DraftArtifact(version=1, markdown="# 标题", summary="标题")
    await service.store.save_thread(state)

    with pytest.raises(ValueError):
        await service.confirm_step(thread.thread_id, ConfirmStepRequest(step_id="course_title"))
