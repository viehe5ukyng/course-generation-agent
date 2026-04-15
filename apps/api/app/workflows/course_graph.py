from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.audit.logger import AuditService, EventBroker
from app.core.schemas import (
    AuditEvent,
    ConstraintKind,
    ConversationConstraint,
    DecisionItem,
    DraftArtifact,
    GenerationRun,
    GenerationRunKind,
    GenerationRunStatus,
    GenerationSessionState,
    InterruptPayload,
    MessageRecord,
    MessageRole,
    RequirementSlot,
    ResumePayload,
    ReviewBatch,
    ReviewCriterionResult,
    ReviewSuggestion,
    SavedArtifactRecord,
    StepStatus,
    ThreadHistoryEntry,
    ThreadState,
    ThreadStatus,
    TimelineEvent,
    VersionRecord,
)
from app.core.settings import Settings
from app.core.step_catalog import SLOT_DEFINITIONS, StepBlueprint, get_slot_definition, get_step_blueprint
from app.llm.deepseek_client import DeepSeekClient
from app.review.rubric import RUBRIC
from app.storage.thread_store import ThreadStore


CONFIRMATION_PATTERNS = [
    r"^(开始生成|开始吧|可以生成|生成吧|就按这个来|没问题|可以|行|好的|确认|开始|继续下一步)$",
    r"(开始生成|可以生成|就按这个来|确认开始|继续下一步)",
]


@dataclass
class CourseGraph:
    settings: Settings
    store: ThreadStore
    broker: EventBroker
    audit: AuditService
    deepseek: DeepSeekClient
    _graph: Any | None = field(default=None, init=False)
    _graph_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _checkpointer: AsyncSqliteSaver | None = field(default=None, init=False)

    @property
    def checkpoint_db_path(self) -> str:
        return str(self.settings.storage_dir / "langgraph_checkpoints.sqlite")

    async def _ensure_graph(self) -> Any:
        if self._graph is not None:
            return self._graph
        async with self._graph_lock:
            if self._graph is not None:
                return self._graph
            import aiosqlite

            conn = await aiosqlite.connect(self.checkpoint_db_path)
            self._checkpointer = AsyncSqliteSaver(conn)
            await self._checkpointer.setup()
            self._graph = self._build_graph().compile(checkpointer=self._checkpointer)
            return self._graph

    async def run_thread(self, thread_id: str) -> None:
        graph = await self._ensure_graph()
        try:
            state = await self.store.get_thread(thread_id)
            config = {"configurable": {"thread_id": thread_id}}
            await graph.ainvoke({"thread_id": thread_id, "resume": False, "state": state.model_dump(mode="json")}, config=config)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            await self.broker.publish(thread_id, {"type": "thread_failed", "thread_id": thread_id, "payload": {"error": str(exc)}})
            await self.audit.record(
                AuditEvent(
                    thread_id=thread_id,
                    event_type="THREAD_FAILED",
                    status="error",
                    error_code=type(exc).__name__,
                    payload_summary={"error": str(exc)},
                )
            )
            raise

    async def resume_thread(self, thread_id: str, resume_value: dict[str, Any]) -> None:
        graph = await self._ensure_graph()
        config = {"configurable": {"thread_id": thread_id}}
        await graph.ainvoke(Command(resume=resume_value), config=config)

    async def get_state_history(self, thread_id: str) -> list[ThreadHistoryEntry]:
        graph = await self._ensure_graph()
        config = {"configurable": {"thread_id": thread_id}}
        history: list[ThreadHistoryEntry] = []
        async for snapshot in graph.aget_state_history(config):
            history.append(
                ThreadHistoryEntry(
                    checkpoint_id=snapshot.config.get("configurable", {}).get("checkpoint_id"),
                    next_nodes=list(snapshot.next) if snapshot.next else [],
                    metadata=snapshot.metadata or {},
                    values=snapshot.values or {},
                )
            )
        return history

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("intake_message", self.intake_message)
        graph.add_node("requirement_gap_check", self.requirement_gap_check)
        graph.add_node("clarify_question", self.clarify_question)
        graph.add_node("confirm_requirements", self.confirm_requirements)
        graph.add_node("decision_update", self.decision_update)
        graph.add_node("source_parse", self.source_parse)
        graph.add_node("generate_step_artifact", self.generate_step_artifact)
        graph.add_node("critique_score", self.critique_score)
        graph.add_node("auto_improve", self.auto_improve)
        graph.add_node("human_review_interrupt", self.human_review_interrupt)
        graph.add_node("approved_feedback_merge", self.approved_feedback_merge)
        graph.add_node("revise_step_artifact", self.revise_step_artifact)
        graph.add_node("completion_gate", self.completion_gate)
        graph.add_node("apply_manual_feedback", self.apply_manual_feedback)

        graph.add_edge(START, "intake_message")
        graph.add_edge("intake_message", "requirement_gap_check")
        graph.add_conditional_edges(
            "requirement_gap_check",
            self.route_after_gap_check,
            {
                "clarify_question": "clarify_question",
                "confirm_requirements": "confirm_requirements",
                "decision_update": "decision_update",
                "apply_manual_feedback": "apply_manual_feedback",
            },
        )
        graph.add_edge("clarify_question", END)
        graph.add_edge("confirm_requirements", END)
        graph.add_edge("decision_update", "source_parse")
        graph.add_edge("source_parse", "generate_step_artifact")
        graph.add_edge("generate_step_artifact", "critique_score")
        graph.add_conditional_edges(
            "critique_score",
            self.route_after_critique_score,
            {
                "auto_improve": "auto_improve",
                "human_review_interrupt": "human_review_interrupt",
            },
        )
        graph.add_edge("auto_improve", "critique_score")
        graph.add_edge("human_review_interrupt", "approved_feedback_merge")
        graph.add_edge("approved_feedback_merge", "revise_step_artifact")
        graph.add_conditional_edges(
            "revise_step_artifact",
            self.route_after_revise_step_artifact,
            {"critique_score": "critique_score", "completion_gate": "completion_gate"},
        )
        graph.add_edge("apply_manual_feedback", "critique_score")
        graph.add_conditional_edges(
            "completion_gate",
            self.route_after_completion_gate,
            {"review_pending": END, "completed": END},
        )
        return graph

    async def _load_state(self, raw_state: dict[str, Any]) -> ThreadState:
        if raw_state.get("state"):
            return ThreadState.model_validate(raw_state["state"])
        return await self.store.get_thread(raw_state["thread_id"])

    async def _save_state(self, state: ThreadState, node_name: str, event_type: str, payload_summary: dict[str, Any]) -> dict[str, Any]:
        await self.store.save_thread(state)
        await self.audit.record(
            AuditEvent(
                thread_id=state.thread_id,
                user_id=state.user_id,
                node_name=node_name,
                event_type=event_type,
                artifact_version=state.draft_artifact.version if state.draft_artifact else None,
                payload_summary=payload_summary,
            )
        )
        await self.broker.publish(
            state.thread_id,
            {"type": "node_update", "thread_id": state.thread_id, "payload": {"node_name": node_name, "status": state.status, **payload_summary}},
        )
        return {"thread_id": state.thread_id, "state": state.model_dump(mode="json"), **payload_summary}

    def _current_step(self, state: ThreadState) -> StepBlueprint:
        return get_step_blueprint(state.current_step_id)

    def _current_step_state(self, state: ThreadState):
        return next((step for step in state.workflow_steps if step.step_id == state.current_step_id), None)

    def _constraint_summary(self, state: ThreadState) -> str:
        active = [item.instruction for item in state.conversation_constraints if item.active]
        return "\n".join(f"- {item}" for item in active) if active else "无额外约束"

    def _start_generation_session(self, state: ThreadState, *, step: StepBlueprint, kind: GenerationRunKind, source_version: int | None = None, revision_goal: str | None = None) -> GenerationSessionState:
        session = GenerationSessionState(step_id=step.step_id, kind=kind, source_version=source_version, revision_goal=revision_goal)
        state.runtime.generation_session = session
        return session

    def _session(self, state: ThreadState) -> GenerationSessionState:
        if state.runtime.generation_session is None:
            state.runtime.generation_session = GenerationSessionState(step_id=state.current_step_id)
        return state.runtime.generation_session

    def _start_run(self, state: ThreadState, *, kind: GenerationRunKind, instruction: str | None = None, source_version: int | None = None) -> GenerationRun:
        run = GenerationRun(
            kind=kind,
            instruction=instruction,
            source_version=source_version,
            model_provider=self.deepseek.profile.chat.provider,
            model_name=self.deepseek.profile.chat.model,
            metadata={"step_id": state.current_step_id},
        )
        state.generation_runs.append(run)
        self._session(state).active_generation_run_id = run.run_id
        return run

    def _complete_run(self, state: ThreadState, *, target_version: int | None = None, preview: str | None = None) -> None:
        run_id = self._session(state).active_generation_run_id
        if not run_id:
            return
        for run in reversed(state.generation_runs):
            if run.run_id == run_id:
                run.status = GenerationRunStatus.COMPLETED
                run.target_version = target_version
                run.output_preview = preview[:200] if preview else None
                run.completed_at = datetime.now(UTC)
                break

    def _extract_banned_terms(self, state: ThreadState) -> list[str]:
        terms: list[str] = []
        for item in state.conversation_constraints:
            if not item.active or item.kind != ConstraintKind.BAN:
                continue
            normalized = item.instruction
            for prefix in ["不要再沿用", "不要再用", "不要使用", "不要用", "不要", "别用", "不能用", "禁止", "避免", "排除"]:
                normalized = normalized.replace(prefix, "")
            for suffix in ["这个", "这种", "案例", "场景", "表达", "说法", "内容", "风格"]:
                normalized = normalized.replace(suffix, "")
            normalized = normalized.strip(" ：:，,。.;；")
            if normalized:
                terms.append(normalized)
        return list(dict.fromkeys(terms))

    async def _enforce_markdown_constraints(self, state: ThreadState, markdown: str, revision_goal: str) -> str:
        banned_terms = self._extract_banned_terms(state)
        violations = [term for term in banned_terms if term and term in markdown]
        if not violations:
            return markdown
        instruction = "当前稿件仍然出现被禁止内容：" + "、".join(violations) + "。必须完全移除这些内容，并替换成不同案例或表达，不能保留原词。"
        return await self.deepseek.improve_markdown(
            markdown=markdown,
            approved_changes=[instruction],
            context_summary=state.decision_summary,
            constraint_summary=self._constraint_summary(state),
            source_version=state.draft_artifact.version if state.draft_artifact else None,
            revision_goal=revision_goal,
        )

    async def _timeline(self, thread_id: str, event_type: str, title: str, detail: str | None = None, payload: dict[str, Any] | None = None) -> None:
        await self.store.append_timeline_event(TimelineEvent(thread_id=thread_id, event_type=event_type, title=title, detail=detail, payload=payload or {}))

    def _slot_summary_for_step(self, state: ThreadState, step: StepBlueprint) -> str:
        lines: list[str] = []
        for slot_id in [*step.required_slots, *step.optional_slots]:
            slot = state.requirement_slots.get(slot_id)
            if slot and slot.value:
                lines.append(f"{slot.label}: {slot.value}")
        return "\n".join(lines) or "暂无"

    def _serialize_requirement_defs(self, step: StepBlueprint) -> list[dict[str, str]]:
        defs = []
        for slot_id in [*step.required_slots, *step.optional_slots]:
            slot = SLOT_DEFINITIONS[slot_id]
            defs.append({"slot_id": slot.slot_id, "label": slot.label, "prompt_hint": slot.prompt_hint, "patterns": list(slot.patterns)})
        return defs

    def _missing_required_slots(self, state: ThreadState, step: StepBlueprint) -> list[dict[str, str]]:
        missing: list[dict[str, str]] = []
        for slot_id in step.required_slots:
            slot = state.requirement_slots.get(slot_id)
            if not slot or not slot.value:
                slot_def = SLOT_DEFINITIONS[slot_id]
                missing.append({"slot_id": slot_id, "label": slot_def.label, "prompt_hint": slot_def.prompt_hint})
        return missing

    def _prior_step_artifacts_summary(self, state: ThreadState, step: StepBlueprint) -> str:
        chunks: list[str] = []
        for prerequisite in step.prerequisite_step_ids:
            record = next((item for item in state.saved_artifacts if item.step_id == prerequisite and item.kind == "generated"), None)
            if not record:
                continue
            try:
                content = Path(record.path).read_text(encoding="utf-8")
            except Exception:
                continue
            chunks.append(f"## {record.label}\n{content[:2000]}")
        return "\n\n".join(chunks) or "暂无"

    async def _persist_current_step_artifact(self, state: ThreadState) -> SavedArtifactRecord | None:
        if state.draft_artifact is None:
            return None
        step_state = self._current_step_state(state)
        if step_state is None:
            return None
        artifact_dir = self.settings.storage_dir / state.thread_id / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        filename = get_step_blueprint(step_state.step_id).artifact_filename
        path = artifact_dir / filename
        path.write_text(state.draft_artifact.markdown, encoding="utf-8")

        existing = next((item for item in state.saved_artifacts if item.step_id == step_state.step_id and item.kind == "generated"), None)
        if existing:
            existing.path = str(path)
            existing.filename = filename
            existing.label = step_state.label
            existing.version += 1
            existing.updated_at = datetime.now(UTC)
            step_state.artifact_id = existing.artifact_id
            return existing

        record = SavedArtifactRecord(step_id=step_state.step_id, label=step_state.label, filename=filename, path=str(path), kind="generated")
        state.saved_artifacts.append(record)
        step_state.artifact_id = record.artifact_id
        return record

    async def intake_message(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        return await self._save_state(state, "intake_message", "GRAPH_NODE_ENTERED", {"message_count": len(state.messages), "step_id": state.current_step_id})

    async def requirement_gap_check(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        latest_user_message = next((m.content for m in reversed(state.messages) if m.role == MessageRole.USER), "")
        current_values = {slot_id: slot.value for slot_id, slot in state.requirement_slots.items() if slot.value}
        requirement_defs = self._serialize_requirement_defs(step)
        extracted = await self.deepseek.extract_requirements(
            latest_user_message=latest_user_message,
            known_requirements=current_values,
            requirement_defs=requirement_defs,
        )
        for definition in requirement_defs:
            slot = state.requirement_slots.get(definition["slot_id"]) or get_slot_definition(definition["slot_id"])
            if not slot.value:
                llm_value = extracted.get(definition["slot_id"])
                if llm_value:
                    slot.value = llm_value.strip()
                    slot.confidence = 0.92
                for pattern in definition["patterns"]:
                    if slot.value:
                        break
                    match = re.search(pattern, latest_user_message)
                    if match:
                        slot.value = match.group(1).strip() if match.groups() else match.group(0).strip()
                        slot.confidence = 0.85
                        break
            if slot.value:
                slot.confirmed = True
            state.requirement_slots[definition["slot_id"]] = slot

        missing = self._missing_required_slots(state, step)
        state.runtime.clarification.missing_requirements = missing
        state.runtime.clarification.next_requirement_to_clarify = missing[0]["slot_id"] if missing else None
        state.runtime.clarification.slot_summary = self._slot_summary_for_step(state, step)
        state.runtime.clarification.latest_user_message = latest_user_message
        state.runtime.clarification.is_confirmation_reply = bool(latest_user_message and any(re.search(pattern, latest_user_message.strip()) for pattern in CONFIRMATION_PATTERNS))
        return await self._save_state(
            state,
            "requirement_gap_check",
            "GRAPH_NODE_COMPLETED",
            {"step_id": step.step_id, "missing_requirements": [item["slot_id"] for item in missing]},
        )

    def route_after_gap_check(self, raw_state: dict[str, Any]) -> str:
        state = ThreadState.model_validate(raw_state["state"])
        if state.runtime.pending_manual_revision_request and state.draft_artifact is not None:
            return "apply_manual_feedback"
        if state.runtime.clarification.missing_requirements:
            return "clarify_question"
        if state.runtime.clarification.is_confirmation_reply:
            return "decision_update"
        return "confirm_requirements"

    async def clarify_question(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        missing_slot_id = state.runtime.clarification.next_requirement_to_clarify
        missing_requirement = next((item for item in state.runtime.clarification.missing_requirements if item["slot_id"] == missing_slot_id), None)
        if missing_requirement is None:
            return await self._save_state(state, "clarify_question", "GRAPH_NODE_SKIPPED", {"reason": "no_missing_requirement"})
        question = ""
        await self.broker.publish(state.thread_id, {"type": "clarification_started", "thread_id": state.thread_id, "payload": {"slot_id": missing_slot_id, "step_id": step.step_id}})
        async for chunk in self.deepseek.stream_clarification({"slot_summary": state.runtime.clarification.slot_summary, "missing_requirement": missing_requirement}):
            question += chunk
            await self.broker.publish(state.thread_id, {"type": "assistant_token", "thread_id": state.thread_id, "payload": {"content": chunk}})
        state.messages.append(MessageRecord(role=MessageRole.ASSISTANT, content=question))
        state.status = ThreadStatus.COLLECTING
        await self.broker.publish(state.thread_id, {"type": "assistant_stream_end", "thread_id": state.thread_id, "payload": {"content": question}})
        await self.broker.publish(state.thread_id, {"type": "clarification_completed", "thread_id": state.thread_id, "payload": {"content": question}})
        await self._timeline(state.thread_id, "clarification_completed", f"{step.label}缺失项追问已发出", detail=question[:160], payload={"step_id": step.step_id})
        return await self._save_state(state, "clarify_question", "CLARIFICATION_REQUESTED", {"question": question[:160], "step_id": step.step_id})

    async def confirm_requirements(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        summary = state.runtime.clarification.slot_summary
        confirmation_message = (
            f"当前在“{step.label}”这一步，我先把会影响这一步生成的关键信息整理一下：\n\n"
            f"{summary}\n\n"
            f"这一步只会生成“{step.label}”相关内容，不会提前展开 {('、'.join(step.forbidden_topics) or '后续步骤')}。"
            " 如果这些信息没问题，你回复“开始生成”即可。"
        )
        state.messages.append(MessageRecord(role=MessageRole.ASSISTANT, content=confirmation_message))
        state.status = ThreadStatus.COLLECTING
        await self.broker.publish(state.thread_id, {"type": "assistant_message", "thread_id": state.thread_id, "payload": {"content": confirmation_message}})
        return await self._save_state(state, "confirm_requirements", "REQUIREMENTS_READY_FOR_CONFIRMATION", {"step_id": step.step_id, "summary": summary[:200]})

    async def decision_update(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        for slot_id in [*step.required_slots, *step.optional_slots]:
            slot = state.requirement_slots.get(slot_id)
            if slot and slot.value and slot.confirmed:
                if not any(item.topic == slot.slot_id and item.value == slot.value for item in state.decision_ledger):
                    state.decision_ledger.append(DecisionItem(topic=slot.slot_id, value=slot.value, reason=f"从{step.label}对话中确认"))
                if slot.slot_id == "constraints":
                    normalized = re.sub(r"\s+", "", slot.value).strip().lower()
                    if normalized and not any(item.normalized_instruction == normalized for item in state.conversation_constraints):
                        state.conversation_constraints.append(ConversationConstraint(kind=ConstraintKind.REQUIRE, instruction=slot.value, normalized_instruction=normalized))
        state.decision_summary = "\n".join(f"{item.topic}: {item.value}" for item in state.decision_ledger)
        await self._timeline(state.thread_id, "requirements_confirmed", f"{step.label}需求已确认", payload={"decision_count": len(state.decision_ledger), "step_id": step.step_id})
        return await self._save_state(state, "decision_update", "DECISION_CONFIRMED", {"decision_count": len(state.decision_ledger), "step_id": step.step_id})

    async def source_parse(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        session = self._session(state)
        source_summary = []
        for document in state.source_manifest:
            if document.extract_status == "parsed":
                preview = " ".join(chunk.text for chunk in document.text_chunks[:2])
                source_summary.append(f"{document.filename}: {preview[:200]}")
        session.source_summary = "\n".join(source_summary) or "无上传资料"
        return await self._save_state(state, "source_parse", "GRAPH_NODE_COMPLETED", {"source_count": len(state.source_manifest), "step_id": state.current_step_id})

    async def generate_step_artifact(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        session = self._start_generation_session(state, step=step, kind=GenerationRunKind.GENERATION, revision_goal=step.generation_goal)
        state.status = ThreadStatus.GENERATING
        session.generated_markdown = ""
        state.draft_artifact = DraftArtifact(version=0, markdown="", summary=f"{step.label}生成中...")
        run = self._start_run(state, kind=GenerationRunKind.GENERATION, instruction=step.generation_goal)
        await self.broker.publish(state.thread_id, {"type": "generation_started", "thread_id": state.thread_id, "payload": {"run_id": run.run_id, "step_id": step.step_id}})
        await self._timeline(state.thread_id, "generation_started", f"开始生成{step.label}", payload={"run_id": run.run_id, "step_id": step.step_id})

        async for chunk in self.deepseek.stream_step_markdown(
            {
                "step_label": step.label,
                "generation_goal": step.generation_goal,
                "required_slots": "\n".join(f"- {SLOT_DEFINITIONS[slot_id].label}" for slot_id in step.required_slots),
                "optional_slots": "\n".join(f"- {SLOT_DEFINITIONS[slot_id].label}" for slot_id in step.optional_slots) or "无",
                "forbidden_topics": "\n".join(f"- {topic}" for topic in step.forbidden_topics) or "无",
                "slot_summary": self._slot_summary_for_step(state, step),
                "source_summary": session.source_summary,
                "prior_step_artifacts": self._prior_step_artifacts_summary(state, step),
                "constraint_summary": self._constraint_summary(state),
            }
        ):
            session.generated_markdown += chunk
            state.draft_artifact.markdown = session.generated_markdown
            await self.broker.publish(state.thread_id, {"type": "generation_chunk", "thread_id": state.thread_id, "payload": {"content": chunk, "step_id": step.step_id}})
        session.generated_markdown = await self._enforce_markdown_constraints(state, session.generated_markdown, step.generation_goal)
        next_version = max([item.version for item in await self.store.list_versions(state.thread_id)], default=0) + 1
        artifact = DraftArtifact(
            version=next_version,
            markdown=session.generated_markdown,
            summary=f"{step.label}已生成。",
            source_version=session.source_version,
            revision_goal=step.generation_goal,
            generation_run_id=session.active_generation_run_id,
        )
        state.draft_artifact = artifact
        state.version_chain.append(VersionRecord(version=artifact.version, artifact_id=artifact.artifact_id, source_version=artifact.source_version, revision_goal=artifact.revision_goal, generation_run_id=artifact.generation_run_id))
        await self.store.upsert_artifact_version(state.thread_id, artifact)
        await self._persist_current_step_artifact(state)
        self._complete_run(state, target_version=artifact.version, preview=artifact.markdown)
        await self.broker.publish(state.thread_id, {"type": "artifact_updated", "thread_id": state.thread_id, "payload": artifact.model_dump(mode="json")})
        await self.broker.publish(state.thread_id, {"type": "generation_completed", "thread_id": state.thread_id, "payload": {"version": artifact.version, "step_id": step.step_id}})
        await self._timeline(state.thread_id, "generation_completed", f"{step.label}已生成", payload={"version": artifact.version, "step_id": step.step_id})
        return await self._save_state(state, "generate_step_artifact", "DRAFT_GENERATED", {"artifact_version": artifact.version, "step_id": step.step_id})

    async def critique_score(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        state.status = ThreadStatus.REVIEW_PENDING
        result = await self.deepseek.review_markdown(markdown=state.draft_artifact.markdown, rubric=RUBRIC, threshold=self.settings.default_review_threshold)
        batch = ReviewBatch(
            step_id=step.step_id,
            draft_version=state.draft_artifact.version,
            total_score=float(result["total_score"]),
            criteria=[ReviewCriterionResult.model_validate(item) for item in result["criteria"]],
            suggestions=[ReviewSuggestion.model_validate(item) for item in result["suggestions"]],
            threshold=self.settings.default_review_threshold,
        )
        state.review_batches.append(batch)
        self._session(state).review_batch_id = batch.review_batch_id
        await self.store.append_review_batch(state.thread_id, batch)
        await self.broker.publish(state.thread_id, {"type": "review_batch", "thread_id": state.thread_id, "payload": batch.model_dump(mode="json")})
        await self.broker.publish(state.thread_id, {"type": "review_ready", "thread_id": state.thread_id, "payload": batch.model_dump(mode="json")})
        await self._timeline(state.thread_id, "review_ready", f"{step.label}评审建议已生成", payload={"review_batch_id": batch.review_batch_id, "score": batch.total_score, "step_id": step.step_id})
        return await self._save_state(state, "critique_score", "REVIEW_BATCH_CREATED", {"review_batch_id": batch.review_batch_id, "score": batch.total_score, "step_id": step.step_id})

    def route_after_critique_score(self, raw_state: dict[str, Any]) -> str:
        state = ThreadState.model_validate(raw_state["state"])
        latest_review = state.review_batches[-1]
        loops = state.runtime.generation_session.auto_optimization_loops if state.runtime.generation_session else 0
        if latest_review.total_score < self.settings.default_review_threshold and loops < self.settings.max_auto_optimization_loops:
            return "auto_improve"
        return "human_review_interrupt"

    async def auto_improve(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        latest_review = state.review_batches[-1]
        state.status = ThreadStatus.REVISING
        session = self._session(state)
        session.auto_optimization_loops += 1
        session.source_version = state.draft_artifact.version if state.draft_artifact else None
        session.revision_goal = f"根据自动评审建议补强{step.label}"
        self._start_run(state, kind=GenerationRunKind.REVISION, instruction=session.revision_goal, source_version=session.source_version)
        session.generated_markdown = await self.deepseek.improve_markdown(
            markdown=state.draft_artifact.markdown,
            approved_changes=[suggestion.suggestion for suggestion in latest_review.suggestions],
            context_summary=state.decision_summary,
            constraint_summary=self._constraint_summary(state),
            source_version=session.source_version,
            revision_goal=session.revision_goal,
        )
        artifact = DraftArtifact(
            version=(state.draft_artifact.version + 1),
            markdown=session.generated_markdown,
            summary=f"{step.label}自动优化版本。",
            source_version=session.source_version,
            revision_goal=session.revision_goal,
            generation_run_id=session.active_generation_run_id,
        )
        state.draft_artifact = artifact
        state.version_chain.append(VersionRecord(version=artifact.version, artifact_id=artifact.artifact_id, source_version=artifact.source_version, revision_goal=artifact.revision_goal, generation_run_id=artifact.generation_run_id))
        await self.store.upsert_artifact_version(state.thread_id, artifact)
        await self._persist_current_step_artifact(state)
        self._complete_run(state, target_version=artifact.version, preview=artifact.markdown)
        await self.broker.publish(state.thread_id, {"type": "revision_started", "thread_id": state.thread_id, "payload": {"loop": session.auto_optimization_loops, "step_id": step.step_id}})
        return await self._save_state(state, "auto_improve", "DRAFT_REVISED", {"mode": "auto", "loop": session.auto_optimization_loops, "step_id": step.step_id})

    async def human_review_interrupt(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        batch = state.review_batches[-1]
        payload = InterruptPayload(review_batch_id=batch.review_batch_id, draft_version=batch.draft_version, total_score=batch.total_score, criteria=batch.criteria, suggestions=batch.suggestions)
        state.runtime.human_review.interrupt_payload = payload
        await self.store.save_thread(state)
        resume_value = interrupt(payload.model_dump(mode="json"))
        state.runtime.human_review.resume_payload = ResumePayload.model_validate(resume_value)
        return await self._save_state(state, "human_review_interrupt", "REVIEW_INTERRUPTED", {"review_batch_id": batch.review_batch_id, "step_id": step.step_id})

    async def approved_feedback_merge(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        payload = state.runtime.human_review.resume_payload
        state.approved_feedback = payload.review_actions if payload else []
        return await self._save_state(state, "approved_feedback_merge", "GRAPH_NODE_COMPLETED", {"approved_count": len(state.approved_feedback), "step_id": state.current_step_id})

    async def revise_step_artifact(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        instructions = [action.edited_suggestion or f"根据人工确认意见补强{step.label}。" for action in state.approved_feedback if action.action != "reject"]
        if not instructions:
            return await self._save_state(state, "revise_step_artifact", "GRAPH_NODE_SKIPPED", {"reason": "no_approved_feedback", "step_id": step.step_id, "revised": False})
        session = self._start_generation_session(state, step=step, kind=GenerationRunKind.REVISION, source_version=state.draft_artifact.version if state.draft_artifact else None, revision_goal=f"根据人工审核意见补强{step.label}")
        self._start_run(state, kind=GenerationRunKind.REVISION, instruction=session.revision_goal, source_version=session.source_version)
        state.status = ThreadStatus.REVISING
        session.generated_markdown = await self.deepseek.improve_markdown(
            markdown=state.draft_artifact.markdown,
            approved_changes=instructions,
            context_summary=state.decision_summary,
            constraint_summary=self._constraint_summary(state),
            source_version=session.source_version,
            revision_goal=session.revision_goal,
        )
        artifact = DraftArtifact(
            version=(state.draft_artifact.version + 1),
            markdown=session.generated_markdown,
            summary=f"{step.label}人工修订版本。",
            source_version=session.source_version,
            revision_goal=session.revision_goal,
            generation_run_id=session.active_generation_run_id,
        )
        state.draft_artifact = artifact
        state.version_chain.append(VersionRecord(version=artifact.version, artifact_id=artifact.artifact_id, source_version=artifact.source_version, revision_goal=artifact.revision_goal, generation_run_id=artifact.generation_run_id))
        await self.store.upsert_artifact_version(state.thread_id, artifact)
        await self._persist_current_step_artifact(state)
        self._complete_run(state, target_version=artifact.version, preview=artifact.markdown)
        await self.broker.publish(state.thread_id, {"type": "revision_started", "thread_id": state.thread_id, "payload": {"approved_count": len(instructions), "step_id": step.step_id}})
        return await self._save_state(state, "revise_step_artifact", "DRAFT_REVISED", {"step_id": step.step_id, "approved_count": len(instructions), "revised": True})

    async def apply_manual_feedback(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        instruction = state.runtime.pending_manual_revision_request or ""
        if not instruction or state.draft_artifact is None:
            return await self._save_state(state, "apply_manual_feedback", "GRAPH_NODE_SKIPPED", {"reason": "no_manual_revision_request", "step_id": step.step_id})
        session = self._start_generation_session(state, step=step, kind=GenerationRunKind.REVISION, source_version=state.draft_artifact.version, revision_goal=instruction)
        self._start_run(state, kind=GenerationRunKind.REVISION, instruction=instruction, source_version=state.draft_artifact.version)
        state.status = ThreadStatus.REVISING
        session.generated_markdown = await self.deepseek.improve_markdown(
            markdown=state.draft_artifact.markdown,
            approved_changes=[instruction],
            context_summary=state.decision_summary,
            constraint_summary=self._constraint_summary(state),
            source_version=state.draft_artifact.version,
            revision_goal=instruction,
        )
        artifact = DraftArtifact(
            version=(state.draft_artifact.version + 1),
            markdown=session.generated_markdown,
            summary=f"{step.label}按用户补充意见修订。",
            source_version=state.draft_artifact.version,
            revision_goal=instruction,
            generation_run_id=session.active_generation_run_id,
        )
        state.draft_artifact = artifact
        state.version_chain.append(VersionRecord(version=artifact.version, artifact_id=artifact.artifact_id, source_version=artifact.source_version, revision_goal=artifact.revision_goal, generation_run_id=artifact.generation_run_id))
        await self.store.upsert_artifact_version(state.thread_id, artifact)
        await self._persist_current_step_artifact(state)
        self._complete_run(state, target_version=artifact.version, preview=artifact.markdown)
        state.runtime.pending_manual_revision_request = None
        return await self._save_state(state, "apply_manual_feedback", "USER_FEEDBACK_APPLIED", {"instruction": instruction[:160], "step_id": step.step_id})

    async def completion_gate(self, raw_state: dict[str, Any]) -> dict[str, Any]:
        state = await self._load_state(raw_state)
        step = self._current_step(state)
        latest_review = state.review_batches[-1]
        if latest_review.step_id != step.step_id or latest_review.draft_version != (state.draft_artifact.version if state.draft_artifact else None):
            state.status = ThreadStatus.REVIEW_PENDING
        else:
            state.status = ThreadStatus.REVIEW_PENDING
        return await self._save_state(state, "completion_gate", "GRAPH_NODE_COMPLETED", {"status": state.status, "score": latest_review.total_score, "step_id": step.step_id})

    def route_after_revise_step_artifact(self, raw_state: dict[str, Any]) -> str:
        revised = bool(raw_state.get("revised"))
        if revised:
            return "critique_score"
        return "completion_gate"

    def route_after_completion_gate(self, raw_state: dict[str, Any]) -> str:
        state = ThreadState.model_validate(raw_state["state"])
        return "review_pending" if state.status == ThreadStatus.REVIEW_PENDING else "completed"
