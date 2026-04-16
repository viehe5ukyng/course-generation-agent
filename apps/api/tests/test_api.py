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
from app.series.scoring import SeriesCriterion, SeriesReviewReport, SeriesSuggestion


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


async def complete_series_guided_flow(service, thread_id: str):
    messages = [
        "A",
        "我要做一套 AI 产品经理系列课，帮助产品经理把 AI 真正用进需求分析和 PRD 输出流程。",
        "B",
        "D 已经会写 PRD，但不会系统用 AI 提升需求分析效率的产品经理",
        "B",
        "D 从把 AI 当问答工具，转变为把 AI 当产品工作流助手",
        "B",
        "B",
        "要求课程内容贴近日常产品工作，并且后半段一定要有真实案例。",
        "开始生成",
    ]
    for content in messages:
        await service.ingest_message(thread_id, content, "default-user")
    return await service.store.get_thread(thread_id)


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
            total_score=88.0,
            threshold=80.0,
            criteria=[
                ReviewCriterionResult(
                    criterion_id="core-problem",
                    name="核心问题",
                    weight=1.0,
                    score=88.0,
                    max_score=100,
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
async def test_series_mode_on_empty_thread_shows_starter_prompt():
    service = get_service()
    thread = await service.create_thread()

    updated = await service.update_mode(thread.thread_id, request=ModeUpdateRequest(mode="series"))

    assert updated.course_mode.value == "series"
    assert updated.messages[-1].role == "assistant"
    content = updated.messages[-1].content
    assert "请选择使用方式" in content
    assert "A. 我没有框架，直接开始制课" in content
    assert "B. 我有现成的框架，直接评分并优化" in content


@pytest.mark.asyncio
async def test_series_framework_file_upload_runs_review_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/threads")
        thread_id = created.json()["data"]["thread"]["thread_id"]

        updated = await client.patch(
            f"/api/v1/threads/{thread_id}/mode",
            json={"mode": "series", "user_id": "default-user"},
        )
        assert updated.status_code == 200

        choice = await client.post(
            f"/api/v1/threads/{thread_id}/messages",
            json={"content": "B", "user_id": "default-user"},
        )
        assert choice.status_code == 200

        framework_markdown = """课程名称：AI 产品经理需求分析系列课
目标学员：已经会写 PRD，但不会系统用 AI 提升需求分析效率的产品经理
学员当前状态：会做基础需求分析，但没有把 AI 接进自己的产品工作流
学员期望状态：可以把 AI 用进需求洞察、PRD 结构化和复盘优化流程
思维转换：从把 AI 当问答工具，到把 AI 当产品工作流助手
课程核心问题：如何让产品经理把 AI 真正用进需求分析与 PRD 输出流程
课程应用场景：日常需求分析、方案拆解、PRD 产出和跨团队协作场景

第1课：认识 AI 产品工作流
内容：明确 AI 在需求分析流程中的角色定位和边界。

第2课：用 AI 做需求洞察
内容：围绕用户反馈、访谈纪要和数据线索完成问题整理。

第3课：用 AI 提升 PRD 输出效率
内容：把需求分析结果转成结构更完整、表达更清晰的 PRD 初稿。

第4课：案例实战与复盘
内容：围绕真实产品需求案例演练完整工作流并复盘优化。
"""

        uploaded = await client.post(
            f"/api/v1/threads/{thread_id}/files?category=framework",
            files={"file": ("series_framework.md", framework_markdown.encode("utf-8"), "text/markdown")},
        )
        assert uploaded.status_code == 200

        thread = await client.get(f"/api/v1/threads/{thread_id}")
        state = thread.json()["data"]["state"]
        assert state["runtime"]["series_guided"]["using_existing_framework"] is True
        assert state["runtime"]["series_guided"]["awaiting_framework_input"] is False
        assert state["draft_artifact"] is not None
        assert state["review_batches"]


@pytest.mark.asyncio
async def test_completion_gate_all_rejected_but_score_passes(monkeypatch: pytest.MonkeyPatch):
    get_service.cache_clear()
    service = get_service()

    async def fake_score_series_framework_markdown(markdown: str, deepseek):
        return SeriesReviewReport(
            total_score=88.0,
            criteria=[
                SeriesCriterion("目标清晰度", "目标清晰度", 10.0, 4.4, 5.0, "整体达标。"),
                SeriesCriterion("内容逻辑性", "内容逻辑性", 20.0, 4.4, 5.0, "整体达标。"),
            ],
            suggestions=[
                SeriesSuggestion(
                    criterion_id="内容逻辑性",
                    problem="案例还可以更贴近真实工作场景。",
                    suggestion="把后半段示例替换成更贴近日常产品协作的案例。",
                    evidence_span="课程框架",
                    severity="medium",
                )
            ],
            summary="达标。",
        )

    monkeypatch.setattr("app.workflows.course_graph.score_series_framework_markdown", fake_score_series_framework_markdown)

    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, request=ModeUpdateRequest(mode="series"))
    state = await complete_series_guided_flow(service, thread.thread_id)
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

    async def fake_score_series_framework_markdown(markdown: str, deepseek):
        return SeriesReviewReport(
            total_score=85.0,
            criteria=[
                SeriesCriterion("目标清晰度", "目标清晰度", 10.0, 4.3, 5.0, "整体达标。"),
                SeriesCriterion("实战性", "实战性", 20.0, 4.3, 5.0, "整体达标。"),
            ],
            suggestions=[
                SeriesSuggestion(
                    criterion_id="实战性",
                    problem="结尾还可以再加强收束感。",
                    suggestion="让最后一课增加更完整的复盘和迁移说明。",
                    evidence_span="课程框架",
                    severity="low",
                )
            ],
            summary="达标。",
        )

    monkeypatch.setattr("app.workflows.course_graph.score_series_framework_markdown", fake_score_series_framework_markdown)

    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, request=ModeUpdateRequest(mode="series"))
    await complete_series_guided_flow(service, thread.thread_id)

    original_state = await service.store.get_thread(thread.thread_id)
    batch = original_state.review_batches[-1]

    get_service.cache_clear()
    restarted = get_service()
    monkeypatch.setattr("app.workflows.course_graph.score_series_framework_markdown", fake_score_series_framework_markdown)

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
async def test_series_mode_runs_guided_questionnaire_before_generation():
    service = get_service()
    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, ModeUpdateRequest(mode="series"))

    state = await service.store.get_thread(thread.thread_id)
    assert state.messages[-1].content.startswith("请选择使用方式")

    await service.ingest_message(
        thread.thread_id,
        "A",
        "default-user",
    )
    state = await service.store.get_thread(thread.thread_id)
    assert state.messages[-1].content.startswith("请输入你的制课想法")

    await service.ingest_message(thread.thread_id, "我要做一套帮助产品经理掌握 AI 需求分析的系列课。", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    assert state.runtime.series_guided.current_question_id == "course_type"
    assert state.messages[-1].content.startswith("系列课结构化问答 1/7")

    await service.ingest_message(thread.thread_id, "B", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    assert state.runtime.series_guided.current_question_id == "target_user"

    await service.ingest_message(thread.thread_id, "D 已经有基础但不会系统应用 AI 的产品经理", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    assert state.requirement_slots["target_user"].value.startswith("已经有基础")


@pytest.mark.asyncio
async def test_series_guided_questionnaire_does_not_wait_for_remote_requirement_extraction(monkeypatch: pytest.MonkeyPatch):
    service = get_service()
    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, ModeUpdateRequest(mode="series"))

    async def fail_if_called(**kwargs):
        raise AssertionError("series guided questionnaire should not call remote requirement extraction")

    monkeypatch.setattr(service.graph.deepseek, "extract_requirements", fail_if_called)

    await service.ingest_message(thread.thread_id, "A", "default-user")
    await service.ingest_message(thread.thread_id, "我要做一门 AI 编程入门系列课。", "default-user")

    state = await service.store.get_thread(thread.thread_id)
    assert state.runtime.series_guided.current_question_id == "course_type"
    assert state.messages[-1].content.startswith("系列课结构化问答 1/7")
    assert state.requirement_slots["topic"].value == "AI 编程入门"


@pytest.mark.asyncio
async def test_series_optional_supplementary_question_can_be_skipped_with_empty_message():
    service = get_service()
    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, ModeUpdateRequest(mode="series"))

    for content in [
        "A",
        "我要做一门 AI 编程入门系列课。",
        "A",
        "A",
        "B",
        "B",
        "B",
        "B",
        "",
    ]:
        await service.ingest_message(thread.thread_id, content, "default-user")

    state = await service.store.get_thread(thread.thread_id)
    answer = state.runtime.series_guided.answers["supplementary_info"]
    assert answer.selected_key == "SKIP"
    assert answer.final_answer == "无补充信息"
    assert state.runtime.series_guided.awaiting_confirmation is True


@pytest.mark.asyncio
async def test_series_mode_existing_framework_scores_immediately():
    service = get_service()
    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, ModeUpdateRequest(mode="series"))

    await service.ingest_message(thread.thread_id, "B", "default-user")
    state = await service.store.get_thread(thread.thread_id)
    assert state.messages[-1].content.startswith("请粘贴你的课程框架")

    framework_markdown = """# 系列课程框架

课程名称：AI 产品经理系列课：从理解到应用的系统训练

目标学员：已经会写 PRD，但不会系统用 AI 提升需求分析效率的产品经理

学员当前状态：目前对 AI 产品经理 有零散理解，但还不能在日常工作提效场景中稳定用起来。

学员期望状态：学完后能独立完成一个具体成果，并能在日常工作提效场景中独立完成关键任务。

思维转换：从把 AI 当问答工具转变为把 AI 当产品工作流助手

课程核心问题：如何让已经会写 PRD，但不会系统用 AI 提升需求分析效率的产品经理围绕 AI 产品经理 建立系统方法，并真正用于日常工作提效场景。

课程应用场景：日常工作提效场景；补充要求：要求课程内容贴近日常产品工作，并且后半段一定要有真实案例。

课程框架：

第1课：建立认知框架
内容：明确 AI 产品经理 的整体地图、学习路径和结果标准。

第2课：拆解核心方法
内容：把 AI 产品经理 拆成可复用的方法步骤和判断标准。

第3课：关键场景演示
内容：围绕日常工作提效场景演示一遍完整做法。

第4课：案例练习与纠错
内容：通过代表性案例练习，暴露常见误区并完成纠偏。

第5课：项目化应用
内容：把前面的方法串成完整工作流，完成一个可交付的小项目。

第6课：复盘与迁移
内容：总结方法边界、复盘关键决策，并给出迁移到新场景的方式。
"""
    await service.ingest_message(thread.thread_id, framework_markdown, "default-user")
    state = await service.store.get_thread(thread.thread_id)

    assert state.runtime.series_guided.using_existing_framework is True
    assert state.draft_artifact is not None
    assert "AI 产品经理系列课" in state.draft_artifact.markdown
    assert state.review_batches


@pytest.mark.asyncio
async def test_series_fallback_generation_infers_specific_topic_from_user_input():
    service = get_service()
    thread = await service.create_thread()
    await service.update_mode(thread.thread_id, ModeUpdateRequest(mode="series"))

    state = await complete_series_guided_flow(service, thread.thread_id)

    assert state.draft_artifact is not None
    assert "AI 产品经理" in state.draft_artifact.markdown
    assert "核心主题" not in state.draft_artifact.markdown


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
