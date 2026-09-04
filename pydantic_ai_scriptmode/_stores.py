"""Durable record stores: a record that survives the process (ADR 0006)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai_scriptmode._record import Record


class SQLiteRecordStore:
    """A `RecordStore` on one SQLite file, so a run parked in one process resumes in another.

    One table, `records(key, record, updated_at)`, created on first use; `put` upserts the record's
    JSON object. The store holds one connection for its life (a fresh connection to `':memory:'`
    would be a fresh database) and runs every statement in a worker thread under a `threading.Lock`
    taken in that thread, so the event loop is never blocked, the connection is never used by two
    threads at once, and the store may be shared by agents on different event loops (an
    `asyncio.Lock` binds to the loop it first waits on). `timeout` is SQLite's busy
    timeout: a writer in another process is waited for that long, then `sqlite3.OperationalError`
    escapes. `put` is last-write-wins; there is no `delete`, and a host prunes by `updated_at`.
    """

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self._connection = sqlite3.connect(path, timeout=timeout, check_same_thread=False)
        self._connection.execute(
            'CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, record TEXT NOT NULL, updated_at TEXT NOT NULL)'
        )
        self._connection.commit()
        self._lock = threading.Lock()

    async def get(self, key: str) -> Record | None:
        """Return the record under `key`, or `None`."""
        row = await asyncio.to_thread(self._select, key)
        return None if row is None else Record.from_dict(json.loads(row))

    async def put(self, key: str, record: Record) -> None:
        """Store the record under `key`, replacing any earlier one."""
        raw = json.dumps(record.to_dict())
        updated_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(self._upsert, key, raw, updated_at)

    def close(self) -> None:
        """Release the connection. The store is unusable afterwards."""
        self._connection.close()

    def _select(self, key: str) -> str | None:
        with self._lock:
            row = self._connection.execute('SELECT record FROM records WHERE key = ?', (key,)).fetchone()
        return None if row is None else row[0]

    def _upsert(self, key: str, raw: str, updated_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                'INSERT INTO records (key, record, updated_at) VALUES (?, ?, ?) '
                'ON CONFLICT(key) DO UPDATE SET record = excluded.record, updated_at = excluded.updated_at',
                (key, raw, updated_at),
            )
