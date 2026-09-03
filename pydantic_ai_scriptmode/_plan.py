"""The plan: inert, serializable data a script compiles to.

Every step is a frozen dataclass whose expressions are stored as source text, not as `ast`
nodes, so a plan round-trips through JSON and a step can be hashed from its authored form.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic_ai_scriptmode._expr import free_names, parse_expression

OnError = Literal['fail', 'skip']


@dataclass(frozen=True)
class Limits:
    """The hard bounds a plan must satisfy before and during execution.

    Defaults follow callscript except `max_total_calls`, raised from 200 so that two fan-outs at the
    per-fan-out limit plus a call fit: models slice at the limit, and 201 against 200 was the most
    common retry in the first real-model trial.
    """

    max_steps: int = 20
    max_items_per_fanout: int = 100
    max_total_calls: int = 500
    """Worst-case calls in one plan: every fan-out at its declared maximum."""
    max_concurrency: int = 5
    """Calls in flight at once, across steps and fan-out items."""
    max_expression_nodes: int = 100_000
    """Evaluation budget shared by every expression in one execution."""
    max_result_bytes: int = 10 * 1024 * 1024
    """Size of one call's JSON-encoded result before it is refused."""
    max_suspend_attempts: int = 5
    """Times one step may park across executions before parking again fails it instead."""


@dataclass(frozen=True)
class CallStep:
    """A step that invokes one folded tool with keyword arguments given as expressions."""

    name: str
    tool: str
    args: dict[str, str] = field(default_factory=dict[str, str])
    """Argument name to expression source."""
    reason: str | None = None
    on_error: OnError = 'fail'
    each: str | None = None
    """Fan-out: expression source for the list to dispatch once per element."""
    each_var: str | None = None
    """The name each element is bound to inside `args` when fanning out."""
    max_items: int | None = None
    """Declared upper bound on `each`; the slice that bounds the fan-out."""
    fallback: str | None = None
    """Error branch: expression source that settles the step when the call fails."""
    error_var: str | None = None
    """Name the error is bound to inside `fallback`."""
    after: tuple[str, ...] = ()
    """Earlier steps that must settle first even though no data flows from them."""
    line: int | None = None

    def references(self) -> set[str]:
        """Step names this step reads, in `args`, `each`, and `fallback`."""
        bound = {n for n in (self.each_var, self.error_var) if n is not None}
        names: set[str] = set()
        for source in (*self.args.values(), self.each, self.fallback):
            if source is not None:
                names |= free_names(parse_expression(source))
        return names - bound


@dataclass(frozen=True)
class DeriveStep:
    """A step that computes a value from earlier steps with one pure expression."""

    name: str
    expr: str
    line: int | None = None

    def references(self) -> set[str]:
        """Step names the expression reads."""
        return free_names(parse_expression(self.expr))


@dataclass(frozen=True)
class GuardStep:
    """A step that ends the run early with `value` when `condition` holds.

    A guard is a fence: every earlier step settles before it is judged and no later step starts
    until it passes.
    """

    name: str
    condition: str
    value: str
    line: int | None = None

    def references(self) -> set[str]:
        """Step names the condition and value read."""
        return free_names(parse_expression(self.condition)) | free_names(parse_expression(self.value))


Step = CallStep | DeriveStep | GuardStep


@dataclass(frozen=True)
class Plan:
    """An ordered list of steps plus the run's output expression."""

    steps: tuple[Step, ...]
    intent: str | None = None
    output: str | None = None
    """Expression source for the run's output; `None` means the last step's value."""

    def step(self, name: str) -> Step:
        """Look a step up by name."""
        for s in self.steps:
            if s.name == name:
                return s
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        """Plain-data form, for storage and inspection."""
        return {
            'intent': self.intent,
            'output': self.output,
            'steps': [{'kind': _kind(s), **asdict(s)} for s in self.steps],
        }


def _kind(step: Step) -> str:
    return {'CallStep': 'call', 'DeriveStep': 'derive', 'GuardStep': 'guard'}[type(step).__name__]


def step_hash(step: Step) -> str:
    """Hash of the authored step, used to recognise an unchanged step across executions.

    `reason` and `line` are left out: audit copy and position are not what the step computes.
    """
    data = {'kind': _kind(step), **asdict(step)}
    data.pop('reason', None)
    data.pop('line', None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=list).encode()).hexdigest()[:32]
