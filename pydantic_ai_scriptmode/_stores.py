"""Durable record stores: a record that survives the process (ADR 0006)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic_ai_scriptmode._record import Record

# SQLite's own text form (`datetime('now')`), so a host prunes with `updated_at < datetime('now', '-7 days')`.
_UPDATED_AT = "strftime('%Y-%m-%d %H:%M:%S', 'now')"


class SQLiteRecordStore:
    """A `RecordStore` on one SQLite file, so a run parked in one process resumes in another.

    One table, `records(key, record, updated_at)`, created on first use; `put` upserts the record's
    JSON object. The store owns one thread and one connection: every statement runs on that thread,
    so the event loop is never blocked, the connection is never shared, agents on different event
    loops can share the store, and `':memory:'` is a store (a fresh connection to it would be a fresh
    database). The file is opened by the first statement, not by the constructor. `timeout` is
    SQLite's busy timeout: a writer in another process is waited for that long, then
    `sqlite3.OperationalError` escapes from the call. `put` is last-write-wins; there is no `delete`,
    and a host prunes by `updated_at`, which is in SQLite's own UTC text form. `close()` waits for the
    statements already queued, then releases the connection and the thread.
    """

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self._path = path
        self._timeout = timeout
        self._connection: sqlite3.Connection | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='SQLiteRecordStore')

    async def get(self, key: str) -> Record | None:
        """Return the record under `key`, or `None`."""
        row = await asyncio.get_running_loop().run_in_executor(self._executor, self._select, key)
        return None if row is None else Record.from_dict(json.loads(row))

    async def put(self, key: str, record: Record) -> None:
        """Store the record under `key`, replacing any earlier one."""
        raw = json.dumps(record.to_dict())
        await asyncio.get_running_loop().run_in_executor(self._executor, self._upsert, key, raw)

    def close(self) -> None:
        """Finish the queued statements, then release the connection and the thread. The store is unusable afterwards."""
        self._executor.submit(self._close_connection)
        self._executor.shutdown(wait=True)

    # Everything below runs on the store's thread.

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._path, timeout=self._timeout)
            with self._connection:
                self._connection.execute(
                    'CREATE TABLE IF NOT EXISTS records '
                    '(key TEXT PRIMARY KEY, record TEXT NOT NULL, updated_at TEXT NOT NULL)'
                )
        return self._connection

    def _select(self, key: str) -> str | None:
        row = self._connect().execute('SELECT record FROM records WHERE key = ?', (key,)).fetchone()
        return None if row is None else row[0]

    def _upsert(self, key: str, raw: str) -> None:
        connection = self._connect()
        with connection:  # `OR REPLACE` rather than `ON CONFLICT`, which needs SQLite 3.24 (found in review)
            connection.execute(
                f'INSERT OR REPLACE INTO records (key, record, updated_at) VALUES (?, ?, {_UPDATED_AT})', (key, raw)
            )

    def _close_connection(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
