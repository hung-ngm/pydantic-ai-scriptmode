from __future__ import annotations

import pydantic_ai.models
import pytest

from pydantic_ai_scriptmode._record import ItemRecord, Record, StepRecord

# Prevent accidental real model requests during tests.
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on the asyncio backend, matching pydantic-ai."""
    return 'asyncio'


@pytest.fixture
def parked_script_tool_record() -> Record:
    """A script tool's record parked in a fan-out, with every field set to something other than its default."""
    return Record(
        steps={
            'topics': StepRecord(hash='a1', status='done', value=['t1', 't2']),
            'scores': StepRecord(
                hash='b2',
                status='suspended',
                items=[ItemRecord('done', 0.4), ItemRecord('suspended'), ItemRecord('skipped', error='boom')],
            ),
            'broken': StepRecord(hash='c3', status='error', error='no such topic'),
        },
        status='suspended',
        at='scores',
        output=None,
        suspend_attempts={'scores': 1},
        parked=['scores'],
        input={'threshold': 0.5},
    )
