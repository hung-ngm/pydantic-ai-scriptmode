"""The record: the serializable outcome of executing a plan, and how a later execution reuses it."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal, Protocol

from pydantic_core import to_jsonable_python

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItemRecord:
        """Rebuild an item from `Record.to_dict`'s object; a missing or unknown key is a `TypeError`."""
        return cls(**_exact(cls, data))


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepRecord:
        """Rebuild a step record from `Record.to_dict`'s object; a missing or unknown key is a `TypeError`."""
        rest = _exact(cls, data)
        items = rest.pop('items')
        return cls(**rest, items=None if items is None else [ItemRecord.from_dict(item) for item in items])


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

    def to_dict(self) -> dict[str, Any]:
        """The record as a JSON-safe object, so a store moves it and nothing else (ADR 0006).

        Values go through `to_jsonable_python`: a custom `Dispatch` may settle a step to a `datetime`
        or a tuple, and a store should not have to know. A tuple comes back as a list.
        """
        return to_jsonable_python(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Record:
        """Rebuild a record from `to_dict`'s object.

        Strict: a missing or unknown key is a `TypeError`, since the package wrote the object and a
        dropped field would be a silent wrong resume (every field has a default, so `cls(**data)`
        alone would not notice).
        """
        rest = _exact(cls, data)
        steps = rest.pop('steps')
        return cls(**rest, steps={name: StepRecord.from_dict(entry) for name, entry in steps.items()})


def _exact(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """A copy of `data` whose keys are exactly `cls`'s fields, or a `TypeError` naming the difference."""
    expected = {f.name for f in fields(cls)}
    missing = sorted(expected - data.keys())
    unknown = sorted(data.keys() - expected)
    if missing or unknown:
        parts = [f'missing {", ".join(missing)}'] if missing else []
        parts += [f'unknown {", ".join(unknown)}'] if unknown else []
        raise TypeError(f'{cls.__name__}.from_dict: {"; ".join(parts)}')
    return dict(data)


class RecordStore(Protocol):
    """Where records live between calls, keyed by a string.

    `run_script` keys its record by the conversation id; a script tool by the conversation id, its
    name, and a hash of its input (ADR 0005). A store treats the key as opaque.
    """

    async def get(self, key: str) -> Record | None:
        """Return the record under `key`, or `None` when there is none yet."""
        ...

    async def put(self, key: str, record: Record) -> None:
        """Store the record under `key`, replacing any earlier one."""
        ...


class InMemoryRecordStore:
    """The default store: a dict for the life of the process."""

    def __init__(self) -> None:
        self._records: dict[str, Record] = {}

    async def get(self, key: str) -> Record | None:
        """Return the record under `key`, or `None`."""
        return self._records.get(key)

    async def put(self, key: str, record: Record) -> None:
        """Store the record for a conversation."""
        self._records[key] = record


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
