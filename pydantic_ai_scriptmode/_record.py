"""The record: the serializable outcome of executing a plan, and how a later execution reuses it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic_ai_scriptmode._plan import Plan, Step, step_hash

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
    suspend_attempts: dict[str, int] = field(default_factory=dict[str, int])
    """Times each step has parked, by name, while it is still parked; cleared when it settles otherwise."""
    parked: list[str] = field(default_factory=list[str])
    """The steps whose suspension the last run surfaced, in plan order; only these may take a resolution."""
    input: Any = None
    """The `input` the last run read. A step that reads `input` is reused only under the same one."""


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


def reusable_steps(plan: Plan, record: Record | None, input: Any = None) -> dict[str, StepRecord]:
    """Settled entries of `record` that the plan can take as given instead of running again.

    A step is reused when the record holds a settled entry (done or skipped) under the same name
    with the same authored hash, and every step it reads is itself reused. The second condition
    goes beyond callscript, which matches on name and hash alone: an unchanged step whose input
    changed would otherwise carry a stale value forward. A step that reads `input` is reused only
    when `input` equals what the record was produced under (`Record.input`); a script tool's record
    is keyed by its input, so there it is as stable as any other step (ADR 0005).
    """
    reused: dict[str, StepRecord] = {}
    if record is None:
        return reused
    for step in plan.steps:
        prior = record.steps.get(step.name)
        if prior is not None and prior.status in ('done', 'skipped') and _same_step(step, prior, reused, record, input):
            reused[step.name] = prior
    return reused


def parked_steps(
    plan: Plan, record: Record | None, reused: dict[str, StepRecord], input: Any = None
) -> dict[str, StepRecord]:
    """Suspended entries of `record` the plan re-enters: same name, same hash, every read step in `reused`.

    A parked step runs again, with the resolution if one was given, and a parked fan-out
    re-dispatches only its parked items. `reused` is `reusable_steps(plan, record, input)`, the
    same rule for its inputs, so the items it carries were produced from the inputs it will see.
    """
    parked: dict[str, StepRecord] = {}
    if record is None:
        return parked
    for step in plan.steps:
        prior = record.steps.get(step.name)
        if prior is not None and prior.status == 'suspended' and _same_step(step, prior, reused, record, input):
            parked[step.name] = prior
    return parked


def _same_step(step: Step, prior: StepRecord, reused: dict[str, StepRecord], record: Record, input: Any) -> bool:
    if prior.hash != step_hash(step):
        return False
    references = step.references()
    if 'input' in references and record.input != input:
        return False
    return all(ref in reused for ref in references if ref != 'input')
