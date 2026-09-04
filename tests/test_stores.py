"""The SQLite store: a record survives the store instance, and so the process (ADR 0006)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pydantic_ai_scriptmode._record import Record, StepRecord
from pydantic_ai_scriptmode._stores import SQLiteRecordStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def store() -> Iterator[SQLiteRecordStore]:
    store = SQLiteRecordStore(':memory:')
    yield store
    store.close()


class TestSQLiteRecordStore:
    async def test_a_missing_key_is_none(self, store: SQLiteRecordStore):
        assert await store.get('conv') is None

    async def test_put_then_get_round_trips_a_parked_script_tool_record(
        self, store: SQLiteRecordStore, parked_script_tool_record: Record
    ):
        await store.put('conv/weak_topics/0123abcd', parked_script_tool_record)
        assert await store.get('conv/weak_topics/0123abcd') == parked_script_tool_record

    async def test_a_second_put_replaces(self, store: SQLiteRecordStore):
        await store.put('conv', Record(steps={'a': StepRecord(hash='h', status='done', value=1)}))
        await store.put('conv', Record(status='error', at='a'))
        assert await store.get('conv') == Record(status='error', at='a')

    async def test_the_file_is_created_on_first_use_and_a_new_store_reads_it(self, tmp_path: Path):
        path = tmp_path / 'records.sqlite'
        first = SQLiteRecordStore(path)
        assert not path.exists()  # construction opens nothing; the first statement does, off the loop
        await first.put('conv', Record(status='suspended', at='x', parked=['x']))
        first.close()
        assert path.exists()
        second = SQLiteRecordStore(path)
        assert await second.get('conv') == Record(status='suspended', at='x', parked=['x'])
        second.close()

    async def test_close_waits_for_a_statement_already_queued(self, tmp_path: Path):
        path = tmp_path / 'records.sqlite'
        store = SQLiteRecordStore(path)
        pending = asyncio.create_task(store.put('conv', Record(status='error', at='x')))
        await asyncio.sleep(0)  # the put has handed its statement to the store's thread
        store.close()
        await pending
        second = SQLiteRecordStore(path)
        assert await second.get('conv') == Record(status='error', at='x')
        second.close()

    async def test_updated_at_compares_with_sqlite_datetime_so_a_host_can_prune(self, tmp_path: Path):
        path = tmp_path / 'records.sqlite'
        store = SQLiteRecordStore(path)
        await store.put('conv', Record())
        store.close()
        connection = sqlite3.connect(path)
        try:
            [(updated_at,)] = connection.execute('SELECT updated_at FROM records').fetchall()
            recent = connection.execute(
                "SELECT count(*) FROM records WHERE updated_at > datetime('now', '-1 minute')"
            ).fetchone()
            stale = connection.execute("DELETE FROM records WHERE updated_at < datetime('now', '-1 minute')").rowcount
        finally:
            connection.close()
        assert len(updated_at) == 19 and updated_at[10] == ' '  # SQLite's own text form, UTC
        assert (recent, stale) == ((1,), 0)
