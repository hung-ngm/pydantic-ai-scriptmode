"""One in-memory store held by a module the Temporal test passes through the sandbox, so it is worker-global."""

from pydantic_ai_scriptmode import InMemoryRecordStore

STORE = InMemoryRecordStore()
