from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.audit.logger import AuditService, EventBroker
from app.core.step_catalog import build_workflow_steps, get_step_blueprint
from app.core.schemas import (
    ArtifactVersionDetail,
    AuditEvent,
    ConfirmStepRequest,
    ConstraintKind,
    ConversationConstraint,
    CourseMode,
    DecisionRecord,
    DraftArtifact,
    GenerationRun,
    GenerationRunKind,
    GenerationRunStatus,
    MessageRecord,
    MessageRole,
    ModeUpdateRequest,
    RegenerateRequest,
    ReviewBatch,
    ReviewCriterionResult,
    ReviewSubmitRequest,
    ReviewSuggestion,
    SavedArtifactRecord,
    SeriesGuidedRuntimeState,
    StepStatus,
    ThreadHistoryEntry,
    ThreadStatus,
    TimelineEvent,
    UploadCategory,
    VersionRecord,
    WorkflowStage,
    WorkflowStepState,
)
from app.files.parser import DocumentParser
from app.review.rubric import RUBRIC
from app.series.decision_scoring import PASS_THRESHOLD as SERIES_PASS_THRESHOLD
from app.series.decision_scoring import format_series_review_report_markdown, score_series_framework_markdown
from app.series.scoring import parse_framework_markdown
from app.storage.thread_store import ThreadStore
from app.workflows.course_graph import CourseGraph

SERIES_STARTER_PROMPT = (
    "请选择使用方式：\n\n"
    "A. 我没有框架，直接开始制课\n\n"
    "B. 我有现成的框架，直接评分并优化\n\n"
    "请输入 A 或 B："
)


def series_framework_to_user_input(framework) -> str:
    return (
        "我已经有一版课程框架，需要基于它继续优化。"
        f"课程名称：{framework.course_name}。"
        f"目标学员：{framework.target_user}。"
        f"课程核心问题：{framework.core_problem}。"
        f"应用场景：{framework.application_scenario}。"
    )


@dataclass
class CourseAgentSupport:
    store: ThreadStore
    broker: EventBroker
    audit: AuditService
    parser: DocumentParser
    graph: CourseGraph
    decision_model_data_dir: str

    def build_workflow_steps(self, mode: CourseMode) -> list[WorkflowStepState]:
        return build_workflow_steps(mode)

    def sync_step_status(self, state) -> None:
        active_found = False
        for step in state.workflow_steps:
            if step.step_id == state.current_step_id:
                if step.status != StepStatus.COMPLETED:
                    step.status = StepStatus.ACTIVE
                active_found = True
            elif step.status != StepStatus.COMPLETED:
                step.status = StepStatus.PENDING
        if not active_found and state.workflow_steps:
            state.current_step_id = state.workflow_steps[-1].step_id
            if state.workflow_steps[-1].status != StepStatus.COMPLETED:
                state.workflow_steps[-1].status = StepStatus.ACTIVE

    def next_step_id(self, state) -> str:
        ids = [item.step_id for item in state.workflow_steps]
        if state.current_step_id not in ids:
            return ids[0] if ids else "step_1"
        index = ids.index(state.current_step_id)
        return ids[min(index + 1, len(ids) - 1)]

    def artifact_filename_for_step(self, step_id: str) -> str:
        return get_step_blueprint(step_id).artifact_filename or f"{step_id}.md"

    async def persist_step_artifact(self, state, *, step_id: str, storage_dir) -> SavedArtifactRecord | None:
        if state.draft_artifact is None:
            return None
        step = next((item for item in state.workflow_steps if item.step_id == step_id), None)
        if step is None:
            return None
        artifact_dir = storage_dir / state.thread_id / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        filename = self.artifact_filename_for_step(step_id)
        path = artifact_dir / filename
        path.write_text(state.draft_artifact.markdown, encoding="utf-8")

        existing = next((item for item in state.saved_artifacts if item.step_id == step_id and item.kind == "generated"), None)
        if existing:
            existing.path = str(path)
            existing.filename = filename
            existing.label = step.label
            existing.version += 1
            existing.updated_at = datetime.now(UTC)
            step.artifact_id = existing.artifact_id
            return existing

        record = SavedArtifactRecord(step_id=step_id, label=step.label, filename=filename, path=str(path), kind="generated")
        state.saved_artifacts.append(record)
        step.artifact_id = record.artifact_id
        return record

    async def record_timeline(self, thread_id: str, event_type: str, title: str, detail: str | None = None, payload: dict | None = None) -> None:
        await self.store.append_timeline_event(TimelineEvent(thread_id=thread_id, event_type=event_type, title=title, detail=detail, payload=payload or {}))

    def normalize_constraint(self, text: str) -> str:
        return re.sub(r"\s+", "", text).strip().lower()

    def extract_constraints(self, content: str, source_message_id: str) -> list[ConversationConstraint]:
        clauses = re.split(r"[，。,；;\n]", content)
        constraints: list[ConversationConstraint] = []
        for clause in clauses:
            normalized = clause.strip()
            if not normalized:
                continue
            if any(token in normalized for token in ["不要", "别用", "不能用", "禁止", "避免", "不要再", "排除"]):
                constraints.append(
                    ConversationConstraint(
                        kind=ConstraintKind.BAN,
                        instruction=normalized,
                        normalized_instruction=self.normalize_constraint(normalized),
                        source_message_id=source_message_id,
                    )
                )
            elif any(token in normalized for token in ["必须", "需要", "要基于", "务必", "请保留", "请使用"]):
                constraints.append(
                    ConversationConstraint(
                        kind=ConstraintKind.REQUIRE,
                        instruction=normalized,
                        normalized_instruction=self.normalize_constraint(normalized),
                        source_message_id=source_message_id,
                    )
                )
        return constraints

    def constraint_summary(self, state) -> str:
        active = [item.instruction for item in state.conversation_constraints if item.active]
        return "\n".join(f"- {item}" for item in active) if active else "无额外约束"


@dataclass
class ThreadUseCases:
    support: CourseAgentSupport
    settings: object

    async def create_thread(self):
        state = await self.support.store.create_thread()
        state.workflow_steps = self.support.build_workflow_steps(state.course_mode)
        state.current_step_id = state.workflow_steps[0].step_id if state.workflow_steps else "course_title"
        await self.support.store.save_thread(state)
        await self.support.audit.record(
            AuditEvent(thread_id=state.thread_id, event_type="THREAD_CREATED", payload_summary={"status": state.status})
        )
        await self.support.record_timeline(state.thread_id, "thread_created", "线程已创建", payload={"status": state.status})
        return await self.support.store.build_summary(state.thread_id)

    async def update_mode(self, thread_id: str, request: ModeUpdateRequest):
        state = await self.support.store.get_thread(thread_id)
        starter_message: MessageRecord | None = None
        state.course_mode = request.mode
        state.workflow_steps = self.support.build_workflow_steps(request.mode)
        state.current_step_id = state.workflow_steps[0].step_id if state.workflow_steps else "course_title"
        state.requirements_confirmed = False
        state.requirement_slots = {}
        state.decision_ledger = []
        state.decision_summary = ""
        state.draft_artifact = None
        state.review_batches = []
        state.approved_feedback = []
        state.runtime.generation_session = None
        state.runtime.pending_manual_revision_request = None
        state.runtime.series_guided = SeriesGuidedRuntimeState(awaiting_entry_mode=request.mode == CourseMode.SERIES)
        if request.mode == CourseMode.SERIES and not state.messages:
            starter_message = MessageRecord(role=MessageRole.ASSISTANT, content=SERIES_STARTER_PROMPT)
            state.messages.append(starter_message)
        await self.support.store.save_thread(state)
        await self.support.record_timeline(thread_id, "mode_changed", "切换了制课模式", detail=request.mode.value)
        if starter_message is not None:
            await self.support.broker.publish(
                thread_id,
                {"type": "assistant_message", "thread_id": thread_id, "payload": {"content": starter_message.content}},
            )
        return state

    async def list_threads(self):
        states = await self.support.store.list_thread_states()
        summaries = [await self.support.store.build_summary(state.thread_id) for state in states]
        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return summaries

    async def confirm_step(self, thread_id: str, request: ConfirmStepRequest):
        state = await self.support.store.get_thread(thread_id)
        current_step = next((step for step in state.workflow_steps if step.step_id == state.current_step_id), None)
        if current_step is None or request.step_id != state.current_step_id:
            raise ValueError("Only the active step can be confirmed")
        if current_step.status != StepStatus.ACTIVE:
            raise ValueError("Current step is not active")

        record = next((item for item in state.saved_artifacts if item.step_id == request.step_id and item.kind == "generated"), None)
        if record is None:
            record = await self.support.persist_step_artifact(state, step_id=request.step_id, storage_dir=self.settings.storage_dir)
        if record is None:
            raise ValueError("Current step has no generated artifact to confirm")

        blueprint = get_step_blueprint(request.step_id)
        if blueprint.needs_review:
            matching_batch = next(
                (batch for batch in reversed(state.review_batches) if batch.step_id == request.step_id and state.draft_artifact and batch.draft_version == state.draft_artifact.version),
                None,
            )
            if matching_batch is None:
                raise ValueError("Current step has not been reviewed yet")
            if matching_batch.total_score < matching_batch.threshold:
                raise ValueError("Current step review score does not meet the threshold")

        current_step.status = StepStatus.COMPLETED
        current_step.confirmed_at = datetime.now(UTC)
        current_step.artifact_id = record.artifact_id

        next_step_id = self.support.next_step_id(state)
        if next_step_id == current_step.step_id:
            state.status = ThreadStatus.COMPLETED
        else:
            state.current_step_id = next_step_id
            self.support.sync_step_status(state)
            state.status = ThreadStatus.COLLECTING
            state.runtime.clarification = state.runtime.clarification.model_copy(update={"missing_requirements": [], "next_requirement_to_clarify": None, "slot_summary": "暂无", "latest_user_message": "", "is_confirmation_reply": False})
            state.runtime.generation_session = None
            state.draft_artifact = None
            state.approved_feedback = []
        await self.support.store.save_thread(state)
        await self.support.record_timeline(
            thread_id,
            "step_confirmed",
            "确认了当前步骤",
            detail=request.step_id,
            payload={"step_id": request.step_id, "artifact_id": record.artifact_id if record else None},
        )
        return state

    async def delete_thread(self, thread_id: str) -> None:
        await self.support.store.delete_thread(thread_id)
        await self.support.audit.record(AuditEvent(thread_id=thread_id, event_type="THREAD_DELETED", payload_summary={"thread_id": thread_id}))

    async def get_history(self, thread_id: str):
        return await self.support.graph.get_state_history(thread_id)

    async def get_timeline(self, thread_id: str):
        return await self.support.store.get_timeline(thread_id)

    async def list_versions(self, thread_id: str) -> list[ArtifactVersionDetail]:
        return await self.support.store.list_versions(thread_id)

    async def get_artifact_version(self, thread_id: str, version: int) -> ArtifactVersionDetail:
        return await self.support.store.get_artifact_version(thread_id, version)


@dataclass
class ConversationUseCases:
    support: CourseAgentSupport

    async def ingest_message(self, thread_id: str, content: str, user_id: str):
        state = await self.support.store.get_thread(thread_id)
        message = MessageRecord(role=MessageRole.USER, content=content)
        state.messages.append(message)
        existing_constraint_keys = {item.normalized_instruction for item in state.conversation_constraints}
        for constraint in self.support.extract_constraints(content, message.message_id):
            if constraint.normalized_instruction not in existing_constraint_keys:
                state.conversation_constraints.append(constraint)
                existing_constraint_keys.add(constraint.normalized_instruction)
        if state.requirements_confirmed and state.draft_artifact is not None:
            state.runtime.pending_manual_revision_request = content
            state.status = ThreadStatus.REVISING
        else:
            state.status = ThreadStatus.COLLECTING
        await self.support.store.save_thread(state)
        await self.support.audit.record(
            AuditEvent(thread_id=thread_id, user_id=user_id, event_type="MESSAGE_RECEIVED", payload_summary={"content_preview": content[:120]})
        )
        await self.support.record_timeline(thread_id, "user_message", "收到用户消息", detail=content[:160], payload={"message_id": message.message_id})
        await self.support.broker.publish(thread_id, {"type": "user_message", "thread_id": thread_id, "payload": {"content": content}})

    async def retract_last_message(self, thread_id: str) -> None:
        state = await self.support.store.get_thread(thread_id)
        if not state.messages or state.messages[-1].role != MessageRole.USER or state.status not in (ThreadStatus.COLLECTING,):
            return
        state.messages.pop()
        if state.messages and state.messages[-1].role == MessageRole.ASSISTANT:
            state.messages.pop()
        await self.support.store.save_thread(state)
        await self.support.record_timeline(thread_id, "message_retracted", "撤回上一条消息")
        await self.support.broker.publish(thread_id, {"type": "message_retracted", "thread_id": thread_id, "payload": {}})

    async def replace_last_message(self, thread_id: str, content: str, user_id: str) -> None:
        state = await self.support.store.get_thread(thread_id)
        if not state.messages or state.status not in (ThreadStatus.COLLECTING, ThreadStatus.PAUSED):
            return
        while state.messages and state.messages[-1].role == MessageRole.ASSISTANT:
            state.messages.pop()
        if not state.messages or state.messages[-1].role != MessageRole.USER:
            return
        state.messages[-1].content = content
        state.messages[-1].meta["edited"] = True
        state.messages[-1].meta["edited_at"] = datetime.now(UTC).isoformat()
        state.status = ThreadStatus.COLLECTING
        state.runtime.pending_manual_revision_request = None
        await self.support.store.save_thread(state)
        await self.support.audit.record(
            AuditEvent(thread_id=thread_id, user_id=user_id, event_type="MESSAGE_REPLACED", payload_summary={"content_preview": content[:120]})
        )
        await self.support.record_timeline(thread_id, "message_replaced", "修改了上一条用户消息", detail=content[:160])
        await self.support.broker.publish(thread_id, {"type": "message_replaced", "thread_id": thread_id, "payload": {"content": content}})


@dataclass
class ArtifactUseCases:
    support: CourseAgentSupport
    settings: object

    async def update_artifact(self, thread_id: str, markdown: str):
        artifact = await self.support.store.update_artifact_content(thread_id, markdown)
        await self.support.audit.record(
            AuditEvent(thread_id=thread_id, event_type="ARTIFACT_EDITED", artifact_version=artifact.version, payload_summary={"length": len(markdown)})
        )
        await self.support.record_timeline(thread_id, "artifact_edited", "人工编辑了课程稿", payload={"version": artifact.version})
        await self.support.broker.publish(thread_id, {"type": "artifact_updated", "thread_id": thread_id, "payload": artifact.model_dump(mode="json")})
        return artifact

    async def upload_file(self, thread_id: str, filename: str, mime_type: str, content: bytes, category: UploadCategory = UploadCategory.CONTEXT) -> None:
        if category == UploadCategory.PACKAGE:
            bucket_dir = "package_uploads"
        elif category == UploadCategory.FRAMEWORK:
            bucket_dir = "framework_uploads"
        else:
            bucket_dir = "context_uploads"
        path = self.settings.storage_dir / thread_id / bucket_dir
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / filename
        file_path.write_bytes(content)
        doc = self.support.parser.parse_file(file_path, mime_type)
        doc.metadata["category"] = category.value
        state = await self.support.store.get_thread(thread_id)
        if category == UploadCategory.FRAMEWORK:
            if state.course_mode != CourseMode.SERIES:
                raise ValueError("只有系列课支持导入现成框架。")
            framework_text = "\n".join(chunk.text for chunk in doc.text_chunks).strip()
            if doc.extract_status != "parsed" or not framework_text:
                raise ValueError("现成框架文件解析失败，请上传可读取的 .md、.docx 或 .doc 文件。")
            framework = parse_framework_markdown(framework_text)
            if not framework.course_name or not framework.lessons:
                raise ValueError("现成框架解析失败，请上传符合 series_framework.md 风格的框架文件。")
            guided = state.runtime.series_guided
            guided.entry_mode = "B"
            guided.awaiting_entry_mode = False
            guided.awaiting_initial_idea = False
            guided.awaiting_framework_input = False
            guided.awaiting_confirmation = False
            guided.completed = True
            guided.using_existing_framework = True
            guided.imported_framework_markdown = framework_text
            guided.initial_user_input = series_framework_to_user_input(framework)
            guided.current_question_id = None
            guided.current_question_prompt = None
            state.runtime.clarification.is_confirmation_reply = True
            state.messages.append(MessageRecord(role=MessageRole.USER, content=f"我导入了现成框架文件：{filename}"))
        state.source_manifest.append(doc)
        state.saved_artifacts.append(
            SavedArtifactRecord(
                step_id="package_upload" if category == UploadCategory.PACKAGE else state.current_step_id,
                label=f"现成框架：{filename}" if category == UploadCategory.FRAMEWORK else filename,
                filename=filename,
                path=str(file_path),
                kind="uploaded" if category == UploadCategory.PACKAGE else "reference",
            )
        )
        await self.support.store.save_thread(state)
        await self.support.audit.record(
            AuditEvent(
                thread_id=thread_id,
                event_type="FILE_UPLOADED",
                artifact_version=state.draft_artifact.version if state.draft_artifact else None,
                payload_summary={"filename": filename, "status": doc.extract_status},
            )
        )
        await self.support.audit.record(AuditEvent(thread_id=thread_id, event_type="FILE_PARSED", payload_summary={"filename": filename, "chunks": len(doc.text_chunks)}))
        await self.support.broker.publish(thread_id, {"type": "file_uploaded", "thread_id": thread_id, "payload": {**doc.model_dump(mode="json"), "category": category.value}})

    async def regenerate(self, thread_id: str, request: RegenerateRequest) -> DraftArtifact:
        state = await self.support.store.get_thread(thread_id)
        base_version = request.base_version or (state.draft_artifact.version if state.draft_artifact else None)
        if base_version is None:
            raise KeyError("No artifact version available for regeneration")
        base_artifact = await self.support.store.get_artifact_version(thread_id, base_version)
        generation_run = GenerationRun(
            kind=GenerationRunKind.REVISION,
            source_version=base_artifact.version,
            instruction=request.instruction,
            model_provider=self.support.graph.deepseek.profile.chat.provider,
            model_name=self.support.graph.deepseek.profile.chat.model,
        )
        state.generation_runs.append(generation_run)
        state.status = ThreadStatus.REVISING
        state.runtime.generation_session = None
        await self.support.store.save_thread(state)
        await self.support.record_timeline(
            thread_id,
            "revision_started",
            "开始基于历史版本重新生成",
            detail=request.instruction,
            payload={"base_version": base_artifact.version, "run_id": generation_run.run_id},
        )
        await self.support.broker.publish(
            thread_id,
            {"type": "revision_started", "thread_id": thread_id, "payload": {"base_version": base_artifact.version, "instruction": request.instruction}},
        )
        instructions = [request.instruction]
        for action in state.approved_feedback:
            if action.action.value == "reject":
                continue
            if action.edited_suggestion:
                instructions.append(action.edited_suggestion)
        if state.course_mode == CourseMode.SERIES:
            markdown = await self.support.graph.deepseek.rewrite_series_framework_markdown(
                markdown=base_artifact.markdown,
                user_input=state.runtime.series_guided.initial_user_input or next((m.content for m in state.messages if m.role == MessageRole.USER), ""),
                guided_answers=self.support.graph._series_guided_answers_text(state),
                approved_changes=instructions,
                constraint_summary=self.support.constraint_summary(state),
                source_version=base_artifact.version,
                revision_goal=request.instruction,
            )
        else:
            markdown = await self.support.graph.deepseek.improve_markdown(
                markdown=base_artifact.markdown,
                approved_changes=instructions,
                context_summary=state.decision_summary,
                constraint_summary=self.support.constraint_summary(state),
                source_version=base_artifact.version,
                revision_goal=request.instruction,
            )
        next_version = max([item.version for item in await self.support.store.list_versions(thread_id)], default=0) + 1
        artifact = DraftArtifact(
            version=next_version,
            markdown=markdown,
            summary="根据人工指令重新生成的新版本课程稿。",
            derived_from_feedback_ids=[item.suggestion_id for item in state.approved_feedback],
            source_version=base_artifact.version,
            revision_goal=request.instruction,
            generation_run_id=generation_run.run_id,
        )
        generation_run.status = GenerationRunStatus.COMPLETED
        generation_run.target_version = next_version
        generation_run.output_preview = markdown[:200]
        generation_run.completed_at = datetime.now(UTC)
        state.draft_artifact = artifact
        state.version_chain.append(
            VersionRecord(
                version=artifact.version,
                artifact_id=artifact.artifact_id,
                source_version=artifact.source_version,
                revision_goal=artifact.revision_goal,
                generation_run_id=artifact.generation_run_id,
                created_at=artifact.created_at,
            )
        )
        await self.support.store.upsert_artifact_version(thread_id, artifact)
        review_message = ""
        review_threshold = self.settings.default_review_threshold
        if state.course_mode == CourseMode.SERIES:
            report = await score_series_framework_markdown(artifact.markdown, self.support.graph.deepseek)
            review_result = {
                "total_score": report.total_score,
                "criteria": [
                    {
                        "criterion_id": item.criterion_id,
                        "name": item.name,
                        "weight": item.weight,
                        "score": item.score,
                        "max_score": item.max_score,
                        "reason": item.reason,
                    }
                    for item in report.criteria
                ],
                "suggestions": [
                    {
                        "criterion_id": item.criterion_id,
                        "problem": item.problem,
                        "suggestion": item.suggestion,
                        "evidence_span": item.evidence_span,
                        "severity": item.severity,
                    }
                    for item in report.suggestions
                ],
            }
            review_threshold = SERIES_PASS_THRESHOLD
            review_message = format_series_review_report_markdown(report)
        else:
            review_result = await self.support.graph.deepseek.review_markdown(markdown=artifact.markdown, rubric=RUBRIC, threshold=self.settings.default_review_threshold)
        batch = ReviewBatch(
            step_id=state.current_step_id,
            draft_version=artifact.version,
            total_score=float(review_result["total_score"]),
            criteria=[ReviewCriterionResult.model_validate(item) for item in review_result["criteria"]],
            suggestions=[ReviewSuggestion.model_validate(item) for item in review_result["suggestions"]],
            threshold=review_threshold,
        )
        state.review_batches.append(batch)
        await self.support.store.append_review_batch(thread_id, batch)
        state.status = ThreadStatus.REVIEW_PENDING
        if review_message:
            state.messages.append(MessageRecord(role=MessageRole.ASSISTANT, content=review_message))
        await self.support.store.save_thread(state)
        await self.support.record_timeline(
            thread_id,
            "revision_completed",
            "基于历史版本生成了新稿",
            payload={"base_version": base_artifact.version, "version": artifact.version, "run_id": generation_run.run_id},
        )
        await self.support.broker.publish(thread_id, {"type": "artifact_updated", "thread_id": thread_id, "payload": artifact.model_dump(mode="json")})
        await self.support.broker.publish(thread_id, {"type": "review_ready", "thread_id": thread_id, "payload": batch.model_dump(mode="json")})
        if review_message:
            await self.support.broker.publish(thread_id, {"type": "assistant_message", "thread_id": thread_id, "payload": {"content": review_message}})
        await self.support.broker.publish(
            thread_id,
            {"type": "revision_completed", "thread_id": thread_id, "payload": {"version": artifact.version, "review_batch_id": batch.review_batch_id}},
        )
        return artifact


@dataclass
class ReviewUseCases:
    support: CourseAgentSupport

    async def export_decision_records(self, thread_id: str | None = None):
        return await self.support.store.list_decision_records(thread_id)

    async def submit_review(self, thread_id: str, batch_id: str, review_request: ReviewSubmitRequest) -> None:
        state = await self.support.store.get_thread(thread_id)
        state.approved_feedback = review_request.review_actions
        state.status = ThreadStatus.REVISING
        latest_batch = state.review_batches[-1] if state.review_batches else None
        suggestions_by_id = {suggestion.suggestion_id: suggestion for suggestion in (latest_batch.suggestions if latest_batch else [])}
        conversation_context = "\n".join(message.content for message in state.messages[-6:] if message.role == MessageRole.USER)
        draft_excerpt = state.draft_artifact.markdown[:1500] if state.draft_artifact else ""
        for action in review_request.review_actions:
            suggestion = suggestions_by_id.get(action.suggestion_id)
            if not suggestion:
                continue
            record = DecisionRecord(
                thread_id=thread_id,
                suggestion_id=action.suggestion_id,
                criterion_id=suggestion.criterion_id,
                user_message_context=conversation_context,
                decision_summary=state.decision_summary,
                draft_excerpt=draft_excerpt,
                model_problem=suggestion.problem,
                model_suggestion=suggestion.suggestion,
                human_action=action.action.value,
                edited_suggestion=action.edited_suggestion,
                reviewer_id=action.reviewer_id,
            )
            await self.support.store.append_decision_record(record)
            self._append_decision_record_jsonl(record)
        await self.support.store.save_thread(state)
        await self.support.audit.record(
            AuditEvent(
                thread_id=thread_id,
                user_id=review_request.submitter_id,
                event_type="REVIEW_ACTION_SUBMITTED",
                payload_summary={"review_batch_id": batch_id, "actions": [item.action for item in review_request.review_actions]},
            )
        )
        await self.support.record_timeline(thread_id, "review_submitted", "人工审核结果已提交", payload={"review_batch_id": batch_id, "action_count": len(review_request.review_actions)})

    def _append_decision_record_jsonl(self, record: DecisionRecord) -> None:
        from pathlib import Path

        output_path = Path(self.support.decision_model_data_dir) / "decision_records.jsonl"
        with output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
