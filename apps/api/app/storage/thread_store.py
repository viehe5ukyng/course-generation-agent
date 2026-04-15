from __future__ import annotations

from datetime import UTC, datetime
from difflib import unified_diff
from uuid import uuid4

from app.core.schemas import (
    ArtifactVersionDetail,
    AuditEvent,
    DecisionRecord,
    DraftArtifact,
    ReviewBatch,
    SourceDocument,
    ThreadState,
    ThreadStatus,
    ThreadSummary,
    TimelineEvent,
    VersionRecord,
)
from app.storage.repositories import (
    ArtifactVersionRepository,
    AuditEventRepository,
    DecisionRecordRepository,
    ReviewBatchRepository,
    SqliteDatabase,
    ThreadRepository,
    TimelineEventRepository,
)


class ThreadNotFoundError(KeyError):
    def __init__(self, thread_id: str) -> None:
        super().__init__(thread_id)
        self.thread_id = thread_id


class ThreadStore:
    def __init__(self, database_url: str) -> None:
        self.database = SqliteDatabase(database_url)
        self.threads = ThreadRepository(self.database)
        self.artifacts = ArtifactVersionRepository(self.database)
        self.reviews = ReviewBatchRepository(self.database)
        self.timeline = TimelineEventRepository(self.database)
        self.audit_events = AuditEventRepository(self.database)
        self.decisions = DecisionRecordRepository(self.database)

    @property
    def db_path(self):
        return self.database.path

    async def create_thread(self, *, user_id: str = "default-user") -> ThreadState:
        state = ThreadState(thread_id=uuid4().hex, user_id=user_id)
        await self.save_thread(state)
        return state

    async def get_thread(self, thread_id: str) -> ThreadState:
        state = await self.threads.get(thread_id)
        if state is None:
            raise ThreadNotFoundError(thread_id)
        return state

    async def list_thread_states(self) -> list[ThreadState]:
        return await self.threads.list()

    async def delete_thread(self, thread_id: str) -> None:
        deleted = await self.threads.delete(thread_id)
        if not deleted:
            raise ThreadNotFoundError(thread_id)
        await self.artifacts.delete_thread(thread_id)
        await self.reviews.delete_thread(thread_id)
        await self.timeline.delete_thread(thread_id)
        await self.audit_events.delete_thread(thread_id)
        await self.decisions.delete_thread(thread_id)

    async def save_thread(self, state: ThreadState) -> ThreadState:
        saved = await self.threads.save(state)
        if state.draft_artifact and state.draft_artifact.version > 0:
            await self.artifacts.upsert(
                state.thread_id,
                ArtifactVersionDetail.model_validate(state.draft_artifact.model_dump(mode="json")),
            )
        for batch in state.review_batches:
            await self.reviews.append(state.thread_id, batch)
        return saved

    async def list_files(self, thread_id: str) -> list[SourceDocument]:
        state = await self.get_thread(thread_id)
        return state.source_manifest

    async def latest_artifact(self, thread_id: str) -> DraftArtifact | None:
        state = await self.get_thread(thread_id)
        return state.draft_artifact

    async def update_artifact_content(self, thread_id: str, markdown: str) -> DraftArtifact:
        state = await self.get_thread(thread_id)
        next_version = 1
        source_version = None
        if state.draft_artifact:
            next_version = state.draft_artifact.version + 1
            source_version = state.draft_artifact.version
        artifact = DraftArtifact(
            version=next_version,
            markdown=markdown,
            summary="人工编辑后保存的课程设计稿。",
            derived_from_feedback_ids=[],
            source_version=source_version,
        )
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
        await self.save_thread(state)
        return artifact

    async def get_review_batch(self, thread_id: str, review_batch_id: str) -> ReviewBatch:
        await self.get_thread(thread_id)
        batch = await self.reviews.get(thread_id, review_batch_id)
        if batch is None:
            raise KeyError(f"Review batch not found: {review_batch_id}")
        return batch

    async def build_summary(self, thread_id: str) -> ThreadSummary:
        state = await self.get_thread(thread_id)
        latest_review = state.review_batches[-1] if state.review_batches else None
        latest_version = state.draft_artifact.version if state.draft_artifact else None
        active_constraints = [item.instruction for item in state.conversation_constraints if item.active]
        current_run = state.generation_runs[-1] if state.generation_runs else None
        first_user_message = next((item.content for item in state.messages if item.role.value == "user"), "")
        title, subtitle = self._derive_sidebar_text(state, first_user_message, active_constraints)
        updated_at = await self.threads.updated_at(thread_id) or datetime.now(UTC)
        return ThreadSummary(
            thread_id=thread_id,
            user_id=state.user_id,
            status=state.status,
            title=title,
            subtitle=subtitle,
            course_mode=state.course_mode,
            current_step_id=state.current_step_id,
            latest_artifact_version=latest_version,
            review_pending=state.status == ThreadStatus.REVIEW_PENDING,
            latest_score=latest_review.total_score if latest_review else None,
            active_constraints=active_constraints,
            pending_review_count=len(latest_review.suggestions) if latest_review else 0,
            last_generation_target=state.draft_artifact.revision_goal if state.draft_artifact else None,
            current_generation_run_id=current_run.run_id if current_run else None,
            updated_at=updated_at,
        )

    def _derive_sidebar_text(self, state: ThreadState, first_user_message: str, active_constraints: list[str]) -> tuple[str, str]:
        def compact(text: str, limit: int = 22) -> str:
            normalized = " ".join(text.strip().split())
            return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"

        topic = (state.requirement_slots.get("topic").value if state.requirement_slots.get("topic") else "") or ""
        grade_level = (state.requirement_slots.get("grade_level").value if state.requirement_slots.get("grade_level") else "") or ""
        audience = (state.requirement_slots.get("audience").value if state.requirement_slots.get("audience") else "") or ""
        objective = (state.requirement_slots.get("objective").value if state.requirement_slots.get("objective") else "") or ""

        cleaned = first_user_message
        for prefix in ["我要做一节", "我要做一个", "我要做", "帮我设计一门", "帮我做一门", "做一门给", "做一门", "帮我做", "请帮我做"]:
            cleaned = cleaned.replace(prefix, "")
        cleaned = cleaned.replace("，", " ").replace("。", " ").strip()

        if topic and grade_level:
            title = compact(f"{grade_level}{topic}课")
        elif topic and audience:
            title = compact(f"{audience}{topic}课")
        elif topic:
            title = compact(f"{topic}课程")
        elif cleaned:
            title = compact(cleaned, 20)
        else:
            title = "未命名对话"

        if state.draft_artifact and state.draft_artifact.revision_goal:
            subtitle = compact(f"正在修订：{state.draft_artifact.revision_goal}", 24)
        elif active_constraints:
            subtitle = compact(active_constraints[0], 24)
        elif objective:
            subtitle = compact(objective, 24)
        elif state.status == ThreadStatus.REVIEW_PENDING:
            subtitle = "已生成，等待处理"
        elif state.status == ThreadStatus.REVISING:
            subtitle = "正在修订内容"
        elif state.status == ThreadStatus.PAUSED:
            subtitle = "已暂停"
        else:
            subtitle = "继续对话"

        return title, subtitle

    async def diff_versions(self, thread_id: str, version: int, prev_version: int) -> str:
        current = await self.get_artifact_version(thread_id, version)
        previous = await self.get_artifact_version(thread_id, prev_version)
        diff = unified_diff(
            previous.markdown.splitlines(),
            current.markdown.splitlines(),
            fromfile=f"v{prev_version}",
            tofile=f"v{version}",
            lineterm="",
        )
        return "\n".join(diff)

    async def list_versions(self, thread_id: str) -> list[ArtifactVersionDetail]:
        await self.get_thread(thread_id)
        return await self.artifacts.list(thread_id)

    async def get_artifact_version(self, thread_id: str, version: int) -> ArtifactVersionDetail:
        await self.get_thread(thread_id)
        artifact = await self.artifacts.get(thread_id, version)
        if artifact is None:
            raise KeyError(f"Artifact version not found: {version}")
        return artifact

    async def upsert_artifact_version(self, thread_id: str, artifact: DraftArtifact | ArtifactVersionDetail) -> None:
        detail = ArtifactVersionDetail.model_validate(artifact.model_dump(mode="json"))
        await self.artifacts.upsert(thread_id, detail)

    async def append_review_batch(self, thread_id: str, batch: ReviewBatch) -> None:
        await self.reviews.append(thread_id, batch)

    async def list_review_batches(self, thread_id: str) -> list[ReviewBatch]:
        await self.get_thread(thread_id)
        return await self.reviews.list(thread_id)

    async def append_timeline_event(self, event: TimelineEvent) -> None:
        await self.timeline.append(event)

    async def get_timeline(self, thread_id: str) -> list[TimelineEvent]:
        await self.get_thread(thread_id)
        return await self.timeline.list(thread_id)

    async def append_audit_event(self, event: AuditEvent) -> None:
        await self.audit_events.append(event)

    async def list_audit_events(self, thread_id: str) -> list[AuditEvent]:
        await self.get_thread(thread_id)
        return await self.audit_events.list(thread_id)

    async def append_decision_record(self, record: DecisionRecord) -> None:
        await self.decisions.append(record)

    async def list_decision_records(self, thread_id: str | None = None) -> list[DecisionRecord]:
        if thread_id is not None:
            await self.get_thread(thread_id)
        return await self.decisions.list(thread_id)
