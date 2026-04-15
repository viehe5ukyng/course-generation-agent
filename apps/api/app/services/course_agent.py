from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.application.course_agent_use_cases import (
    ArtifactUseCases,
    ConversationUseCases,
    CourseAgentSupport,
    ReviewUseCases,
    ThreadUseCases,
)
from app.audit.logger import AuditService, EventBroker
from app.core.schemas import ConfirmStepRequest, ModeUpdateRequest, RegenerateRequest, ReviewSubmitRequest, ThreadStatus, UploadCategory
from app.core.settings import Settings
from app.files.parser import DocumentParser
from app.storage.thread_store import ThreadStore
from app.workflows.course_graph import CourseGraph


@dataclass
class CourseAgentService:
    settings: Settings
    store: ThreadStore
    broker: EventBroker
    audit: AuditService
    parser: DocumentParser
    graph: CourseGraph
    _active_thread_tasks: dict[str, asyncio.Task] = field(default_factory=dict)

    def __post_init__(self) -> None:
        support = CourseAgentSupport(
            store=self.store,
            broker=self.broker,
            audit=self.audit,
            parser=self.parser,
            graph=self.graph,
            decision_model_data_dir=str(self.settings.decision_model_data_dir),
        )
        self.threads = ThreadUseCases(support=support, settings=self.settings)
        self.conversation = ConversationUseCases(support=support)
        self.artifacts = ArtifactUseCases(support=support, settings=self.settings)
        self.reviews = ReviewUseCases(support=support)

    def _spawn_thread_task(self, thread_id: str, coroutine: asyncio.Future) -> None:
        existing = self._active_thread_tasks.get(thread_id)
        if existing and not existing.done():
            existing.cancel()

        task = asyncio.create_task(coroutine)
        self._active_thread_tasks[thread_id] = task

        def _finalize(completed: asyncio.Task) -> None:
            current = self._active_thread_tasks.get(thread_id)
            if current is completed:
                self._active_thread_tasks.pop(thread_id, None)
            try:
                completed.result()
            except asyncio.CancelledError:
                return
            except Exception:
                return

        task.add_done_callback(_finalize)

    async def create_thread(self):
        return await self.threads.create_thread()

    async def update_mode(self, thread_id: str, request: ModeUpdateRequest):
        return await self.threads.update_mode(thread_id, request)

    async def list_threads(self):
        return await self.threads.list_threads()

    async def confirm_step(self, thread_id: str, request: ConfirmStepRequest):
        return await self.threads.confirm_step(thread_id, request)

    async def delete_thread(self, thread_id: str) -> None:
        await self.threads.delete_thread(thread_id)

    async def ingest_message(self, thread_id: str, content: str, user_id: str) -> None:
        await self.conversation.ingest_message(thread_id, content, user_id)
        if self.settings.app_env == "test":
            await self.graph.run_thread(thread_id)
        else:
            self._spawn_thread_task(thread_id, self.graph.run_thread(thread_id))

    async def update_artifact(self, thread_id: str, markdown: str):
        return await self.artifacts.update_artifact(thread_id, markdown)

    async def upload_file(self, thread_id: str, filename: str, mime_type: str, content: bytes, category: UploadCategory = UploadCategory.CONTEXT) -> None:
        await self.artifacts.upload_file(thread_id, filename, mime_type, content, category)

    async def retract_last_message(self, thread_id: str) -> None:
        await self.conversation.retract_last_message(thread_id)

    async def replace_last_message(self, thread_id: str, content: str, user_id: str) -> None:
        await self.conversation.replace_last_message(thread_id, content, user_id)
        if self.settings.app_env == "test":
            await self.graph.run_thread(thread_id)
        else:
            self._spawn_thread_task(thread_id, self.graph.run_thread(thread_id))

    async def pause_thread(self, thread_id: str) -> None:
        state = await self.store.get_thread(thread_id)
        state.runtime.pause.status_before_pause = state.status
        state.runtime.pause.requested = True
        active_task = self._active_thread_tasks.get(thread_id)
        if active_task and not active_task.done():
            active_task.cancel()
            try:
                await active_task
            except asyncio.CancelledError:
                pass
        state.status = ThreadStatus.PAUSED
        await self.store.save_thread(state)
        await self.audit.record(
            self.audit_event(thread_id=thread_id, user_id=state.user_id, event_type="THREAD_PAUSED", payload_summary={"status_before_pause": state.runtime.pause.status_before_pause})
        )
        await self.broker.publish(thread_id, {"type": "thread_paused", "thread_id": thread_id, "payload": {"status_before_pause": state.runtime.pause.status_before_pause}})

    async def resume_paused_thread(self, thread_id: str) -> None:
        state = await self.store.get_thread(thread_id)
        previous = state.runtime.pause.status_before_pause or ThreadStatus.COLLECTING
        state.status = previous
        state.runtime.pause.requested = False
        await self.store.save_thread(state)
        await self.audit.record(self.audit_event(thread_id=thread_id, user_id=state.user_id, event_type="THREAD_RESUMED", payload_summary={"restored_status": previous}))
        await self.broker.publish(thread_id, {"type": "thread_resumed", "thread_id": thread_id, "payload": {"restored_status": previous}})
        if self.settings.app_env == "test":
            await self.graph.run_thread(thread_id)
        else:
            self._spawn_thread_task(thread_id, self.graph.run_thread(thread_id))

    async def get_history(self, thread_id: str):
        return await self.threads.get_history(thread_id)

    async def get_timeline(self, thread_id: str):
        return await self.threads.get_timeline(thread_id)

    async def list_versions(self, thread_id: str):
        return await self.threads.list_versions(thread_id)

    async def get_artifact_version(self, thread_id: str, version: int):
        return await self.threads.get_artifact_version(thread_id, version)

    async def export_decision_records(self, thread_id: str | None = None):
        return await self.reviews.export_decision_records(thread_id)

    async def submit_review(self, thread_id: str, batch_id: str, review_request: ReviewSubmitRequest) -> None:
        await self.reviews.submit_review(thread_id, batch_id, review_request)
        resume_value = {
            "review_batch_id": batch_id,
            "review_actions": [item.model_dump(mode="json") for item in review_request.review_actions],
            "submitter_id": review_request.submitter_id,
        }
        if self.settings.app_env == "test":
            await self.graph.resume_thread(thread_id, resume_value)
        else:
            self._spawn_thread_task(thread_id, self.graph.resume_thread(thread_id, resume_value))

    async def regenerate(self, thread_id: str, request: RegenerateRequest):
        return await self.artifacts.regenerate(thread_id, request)

    def audit_event(self, *, thread_id: str, user_id: str, event_type: str, payload_summary: dict):
        from app.core.schemas import AuditEvent

        return AuditEvent(thread_id=thread_id, user_id=user_id, event_type=event_type, payload_summary=payload_summary)
