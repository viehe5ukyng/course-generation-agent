from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from app.core.schemas import AuditEvent
from app.storage.thread_store import ThreadStore


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "payload"):
            base["payload"] = record.payload
        return json.dumps(base, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


class EventBroker:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    def subscribe(self, thread_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[thread_id].append(queue)
        return queue

    def unsubscribe(self, thread_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._queues.get(thread_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues and thread_id in self._queues:
            del self._queues[thread_id]

    async def publish(self, thread_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._queues.get(thread_id, [])):
            await queue.put(event)


class AuditService:
    def __init__(self, broker: EventBroker, store: ThreadStore | None = None) -> None:
        self.logger = logging.getLogger("course-agent.audit")
        self._events: dict[str, list[AuditEvent]] = defaultdict(list)
        self._broker = broker
        self._store = store

    async def record(self, event: AuditEvent) -> None:
        self._events[event.thread_id].append(event)
        if self._store is not None:
            await self._store.append_audit_event(event)
        self.logger.info(event.event_type, extra={"payload": event.model_dump(mode="json")})
        await self._broker.publish(
            event.thread_id,
            {
                "type": "audit_event",
                "thread_id": event.thread_id,
                "payload": event.model_dump(mode="json"),
            },
        )

    async def list_events(self, thread_id: str) -> list[AuditEvent]:
        if self._store is not None:
            return await self._store.list_audit_events(thread_id)
        return self._events.get(thread_id, [])
