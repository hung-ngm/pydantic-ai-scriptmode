"""The record: the serializable outcome of executing a plan, and how a later execution reuses it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic_ai_scriptmode._plan import Plan, step_hash

StepStatus = Literal['done', 'skipped', 'error', 'returned', 'suspended']
ItemStatus = Literal['done', 'skipped', 'suspended']
RunStatus = Literal['done', 'returned', 'error', 'suspended']


@dataclass
class ItemRecord:
    """One fan-out item's outcome, kept while the step is parked so a resume re-dispatches only the parked items.

    An item that failed is `skipped` (the step had `_on_error='skip'`; otherwise the step failed
    and nothing is kept). A failed item's message is in `error`.
    """

    status: ItemStatus
    value: Any = None
    error: str | None = None


@dataclass
class StepRecord:
    """The settled outcome of one step: its authored hash and value or error.

    `done` and `skipped` are reusable. `error`, `returned`, and `suspended` are re-entry points:
    the step runs again on the next execution, `suspended` with the resolution it was waiting for.
    """

    hash: str
    status: StepStatus
    value: Any = None
    error: str | None = None
    items: list[ItemRecord] | None = None
    """Per-item outcomes of a parked fan-out; `None` for anything else."""


@dataclass
class Record:
    """Latest outcome per step name across every execution in a conversation, plus the last run's status."""

    steps: dict[str, StepRecord] = field(default_factory=dict[str, StepRecord])
    status: RunStatus = 'done'
    at: str | None = None
    """The step the last run returned, failed, or first suspended at."""
    output: Any = None


class RecordStore(Protocol):
    """Where records live between `run_script` calls, keyed by conversation id."""

    async def get(self, conversation_id: str) -> Record | None:
        """Return the record for a conversation, or `None` when there is none yet."""
        ...

    async def put(self, conversation_id: str, record: Record) -> None:
        """Store the record for a conversation, replacing any earlier one."""
        ...


class InMemoryRecordStore:
    """The default store: a dict for the life of the process."""

    def __init__(self) -> None:
        self._records: dict[str, Record] = {}

    async def get(self, conversation_id: str) -> Record | None:
        """Return the record for a conversation, or `None`."""
        return self._records.get(conversation_id)

    async def put(self, conversation_id: str, record: Record) -> None:
        """Store the record for a conversation."""
        self._records[conversation_id] = record


def reusable_steps(plan: Plan, record: Record | None) -> dict[str, StepRecord]:
    """Settled entries of `record` that the plan can take as given instead of running again.

    A step is reused when the record holds a settled entry (done or skipped) under the same name
    with the same authored hash, and every step it reads is itself reused. The second condition
    goes beyond callscript, which matches on name and hash alone: an unchanged step whose input
    changed would otherwise carry a stale value forward. A step that reads `input` is never
    reused, since `input` is not part of the record.
    """
    reused: dict[str, StepRecord] = {}
    if record is None:
        return reused
    for step in plan.steps:
        prior = record.steps.get(step.name)
        if prior is None or prior.status not in ('done', 'skipped') or prior.hash != step_hash(step):
            continue
        references = step.references()
        if 'input' in references or any(ref not in reused for ref in references):
            continue
        reused[step.name] = prior
    return reused
