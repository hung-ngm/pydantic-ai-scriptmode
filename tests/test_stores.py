"""The SQLite store: a record survives the store instance, and so the process (ADR 0006)."""

from __future__ import annotations

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
        await first.put('conv', Record(status='suspended', at='x', parked=['x']))
        first.close()
        assert path.exists()
        second = SQLiteRecordStore(path)
        assert await second.get('conv') == Record(status='suspended', at='x', parked=['x'])
        second.close()

    async def test_updated_at_lets_a_host_prune(self, tmp_path: Path):
        path = tmp_path / 'records.sqlite'
        store = SQLiteRecordStore(path)
        await store.put('conv', Record())
        store.close()
        with sqlite3.connect(path) as connection:
            rows = connection.execute('SELECT key, updated_at FROM records').fetchall()
        connection.close()
        assert len(rows) == 1
        assert rows[0][0] == 'conv'
        assert rows[0][1].endswith('+00:00')
