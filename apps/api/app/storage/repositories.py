from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import aiosqlite

from app.core.schemas import (
    ArtifactVersionDetail,
    AuditEvent,
    DecisionRecord,
    ReviewBatch,
    ThreadState,
    TimelineEvent,
)


class SqliteDatabase:
    def __init__(self, database_url: str) -> None:
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._db_path = self._resolve_sqlite_path(database_url)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @property
    def path(self) -> Path:
        return self._db_path

    def _resolve_sqlite_path(self, database_url: str) -> Path:
        if database_url == ":memory:":
            return Path(":memory:")
        parsed = urlparse(database_url)
        if parsed.scheme.startswith("sqlite"):
            raw_path = parsed.path or database_url.split(":///")[-1]
            if raw_path in {":memory:", "/:memory:"}:
                return Path(":memory:")
            if raw_path.startswith("/./"):
                return Path(raw_path[1:])
            if raw_path.startswith("/") and raw_path != "/:memory:":
                return Path(raw_path)
            return Path(raw_path.lstrip("/"))
        raise ValueError(f"Unsupported database url: {database_url}")

    async def connect(self) -> aiosqlite.Connection:
        await self._ensure_initialized()
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.executescript(
                    """
                    PRAGMA journal_mode=WAL;

                    CREATE TABLE IF NOT EXISTS threads (
                        thread_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        state_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS artifact_versions (
                        thread_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(thread_id, version)
                    );

                    CREATE TABLE IF NOT EXISTS review_batches (
                        review_batch_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        draft_version INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS timeline_events (
                        event_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        detail TEXT,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS decision_records (
                        record_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                await conn.commit()
            self._initialized = True


class ThreadRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    async def create(self, state: ThreadState) -> ThreadState:
        return await self.save(state)

    async def get(self, thread_id: str) -> ThreadState | None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute("SELECT state_json FROM threads WHERE thread_id = ?", (thread_id,))
                row = await cursor.fetchone()
                if row is None:
                    return None
                return ThreadState.model_validate(json.loads(row["state_json"]))
            finally:
                await conn.close()

    async def list(self) -> list[ThreadState]:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute("SELECT state_json FROM threads")
                rows = await cursor.fetchall()
            finally:
                await conn.close()
        return [ThreadState.model_validate(json.loads(row["state_json"])) for row in rows]

    async def delete(self, thread_id: str) -> bool:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute("SELECT thread_id FROM threads WHERE thread_id = ?", (thread_id,))
                row = await cursor.fetchone()
                if row is None:
                    return False
                await conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
                await conn.commit()
                return True
            finally:
                await conn.close()

    async def save(self, state: ThreadState) -> ThreadState:
        updated_at = datetime.now(UTC).isoformat()
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute(
                    """
                    INSERT INTO threads(thread_id, user_id, state_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        state.thread_id,
                        state.user_id,
                        json.dumps(state.model_dump(mode="json"), ensure_ascii=False),
                        updated_at,
                    ),
                )
                await conn.commit()
                return state
            finally:
                await conn.close()

    async def updated_at(self, thread_id: str) -> datetime | None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute("SELECT updated_at FROM threads WHERE thread_id = ?", (thread_id,))
                row = await cursor.fetchone()
            finally:
                await conn.close()
        if row is None:
            return None
        return datetime.fromisoformat(row["updated_at"])


class ArtifactVersionRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    async def upsert(self, thread_id: str, artifact: ArtifactVersionDetail) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute(
                    """
                    INSERT INTO artifact_versions(thread_id, version, payload_json, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(thread_id, version) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at
                    """,
                    (
                        thread_id,
                        artifact.version,
                        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False),
                        artifact.created_at.isoformat(),
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def list(self, thread_id: str) -> list[ArtifactVersionDetail]:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(
                    """
                    SELECT payload_json
                    FROM artifact_versions
                    WHERE thread_id = ?
                    ORDER BY version ASC
                    """,
                    (thread_id,),
                )
                rows = await cursor.fetchall()
            finally:
                await conn.close()
        return [ArtifactVersionDetail.model_validate(json.loads(row["payload_json"])) for row in rows]

    async def get(self, thread_id: str, version: int) -> ArtifactVersionDetail | None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(
                    """
                    SELECT payload_json
                    FROM artifact_versions
                    WHERE thread_id = ? AND version = ?
                    """,
                    (thread_id, version),
                )
                row = await cursor.fetchone()
            finally:
                await conn.close()
        if row is None:
            return None
        return ArtifactVersionDetail.model_validate(json.loads(row["payload_json"]))

    async def delete_thread(self, thread_id: str) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute("DELETE FROM artifact_versions WHERE thread_id = ?", (thread_id,))
                await conn.commit()
            finally:
                await conn.close()


class ReviewBatchRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    async def append(self, thread_id: str, batch: ReviewBatch) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO review_batches(review_batch_id, thread_id, draft_version, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        batch.review_batch_id,
                        thread_id,
                        batch.draft_version,
                        json.dumps(batch.model_dump(mode="json"), ensure_ascii=False),
                        batch.created_at.isoformat(),
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def list(self, thread_id: str) -> list[ReviewBatch]:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(
                    """
                    SELECT payload_json
                    FROM review_batches
                    WHERE thread_id = ?
                    ORDER BY created_at ASC
                    """,
                    (thread_id,),
                )
                rows = await cursor.fetchall()
            finally:
                await conn.close()
        return [ReviewBatch.model_validate(json.loads(row["payload_json"])) for row in rows]

    async def get(self, thread_id: str, review_batch_id: str) -> ReviewBatch | None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(
                    """
                    SELECT payload_json
                    FROM review_batches
                    WHERE thread_id = ? AND review_batch_id = ?
                    """,
                    (thread_id, review_batch_id),
                )
                row = await cursor.fetchone()
            finally:
                await conn.close()
        if row is None:
            return None
        return ReviewBatch.model_validate(json.loads(row["payload_json"]))

    async def delete_thread(self, thread_id: str) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute("DELETE FROM review_batches WHERE thread_id = ?", (thread_id,))
                await conn.commit()
            finally:
                await conn.close()


class TimelineEventRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    async def append(self, event: TimelineEvent) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO timeline_events(event_id, thread_id, event_type, title, detail, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.thread_id,
                        event.event_type,
                        event.title,
                        event.detail,
                        json.dumps(event.payload, ensure_ascii=False),
                        event.created_at.isoformat(),
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def list(self, thread_id: str) -> list[TimelineEvent]:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(
                    """
                    SELECT event_id, thread_id, event_type, title, detail, payload_json, created_at
                    FROM timeline_events
                    WHERE thread_id = ?
                    ORDER BY created_at ASC
                    """,
                    (thread_id,),
                )
                rows = await cursor.fetchall()
            finally:
                await conn.close()
        return [
            TimelineEvent(
                event_id=row["event_id"],
                thread_id=row["thread_id"],
                event_type=row["event_type"],
                title=row["title"],
                detail=row["detail"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def delete_thread(self, thread_id: str) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute("DELETE FROM timeline_events WHERE thread_id = ?", (thread_id,))
                await conn.commit()
            finally:
                await conn.close()


class AuditEventRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    async def append(self, event: AuditEvent) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO audit_events(event_id, thread_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.thread_id,
                        json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
                        event.timestamp.isoformat(),
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def list(self, thread_id: str) -> list[AuditEvent]:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(
                    """
                    SELECT payload_json
                    FROM audit_events
                    WHERE thread_id = ?
                    ORDER BY created_at ASC
                    """,
                    (thread_id,),
                )
                rows = await cursor.fetchall()
            finally:
                await conn.close()
        return [AuditEvent.model_validate(json.loads(row["payload_json"])) for row in rows]

    async def delete_thread(self, thread_id: str) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute("DELETE FROM audit_events WHERE thread_id = ?", (thread_id,))
                await conn.commit()
            finally:
                await conn.close()


class DecisionRecordRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    async def append(self, record: DecisionRecord) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO decision_records(record_id, thread_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.record_id,
                        record.thread_id,
                        json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
                        record.created_at.isoformat(),
                    ),
                )
                await conn.commit()
            finally:
                await conn.close()

    async def list(self, thread_id: str | None = None) -> list[DecisionRecord]:
        query = """
            SELECT payload_json
            FROM decision_records
            {where_clause}
            ORDER BY created_at ASC
        """
        params: tuple[str, ...] = ()
        where_clause = ""
        if thread_id is not None:
            where_clause = "WHERE thread_id = ?"
            params = (thread_id,)
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                cursor = await conn.execute(query.format(where_clause=where_clause), params)
                rows = await cursor.fetchall()
            finally:
                await conn.close()
        return [DecisionRecord.model_validate(json.loads(row["payload_json"])) for row in rows]

    async def delete_thread(self, thread_id: str) -> None:
        async with self.database.lock:
            conn = await self.database.connect()
            try:
                await conn.execute("DELETE FROM decision_records WHERE thread_id = ?", (thread_id,))
                await conn.commit()
            finally:
                await conn.close()
