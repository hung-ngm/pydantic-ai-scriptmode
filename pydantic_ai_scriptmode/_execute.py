"""Execute a plan: a dataflow scheduler that can only invoke folded tools through `dispatch`.

The engine knows nothing about Pydantic AI. It evaluates expressions with the bounded
interpreter, asks `dispatch` to perform each call, and produces a `Record`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic_ai_scriptmode._expr import EvalError, Evaluator, NodeBudget, holds_function_value, parse_expression
from pydantic_ai_scriptmode._plan import CallStep, DeriveStep, GuardStep, Limits, Plan, Step, step_hash
from pydantic_ai_scriptmode._record import ItemRecord, Record, RunStatus, StepRecord, parked_steps, reusable_steps


class Dispatch(Protocol):
    """Performs one call of `step` with evaluated `args` and returns the tool's result.

    Raise `CallError` for a failure the script may handle with its error branch, or `Suspend` to
    park the call on a resolution it needs first. Any other exception propagates out of
    `execute_plan` untouched. `resolution` is `None` except when a parked call is re-dispatched
    with the answer it waited for (`execute_plan(resolutions=...)`).
    """

    async def __call__(self, step: CallStep, args: dict[str, Any], *, resolution: Any = None) -> Any: ...


def _as_list(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None  # pyright: ignore[reportUnknownVariableType]


class CallError(Exception):
    """A call failed in a way the script can handle: the tool raised, refused, or was denied."""


class Suspend(Exception):
    """A call is parked on a resolution: the step settles `suspended` and the run parks once nothing else can settle.

    `payload` is whatever the dispatch wants the resolver to see; it travels on `ExecuteResult`,
    never on the record.
    """

    def __init__(self, payload: Any = None) -> None:
        super().__init__('suspended')
        self.payload = payload


Suspension = tuple[str, int | None, Any]
"""`(step name, fan-out item index or None, payload)` for one parked call."""


class _ItemsParked(Exception):
    """Raised by `collect_items` when a fan-out has a parked item: the step settles `suspended` with `items`."""

    def __init__(self, parked: list[tuple[int | None, Any]], items: list[ItemRecord]) -> None:
        super().__init__('items parked')
        self.parked = parked
        self.items = items


class PlanExecutionError(Exception):
    """The engine could not make progress, which validation should have prevented."""


@dataclass
class ExecuteResult:
    """How the run settled, its output, and the record to store."""

    status: RunStatus
    output: Any
    record: Record
    at: str | None = None
    error: str | None = None
    suspensions: list[Suspension] = field(default_factory=list[Suspension])
    """Every parked call, in plan order, when `status` is `suspended`."""


@dataclass
class Runner:
    """One execution of one plan. Holds the settled environment and drives the steps.

    `execute_plan` builds a runner and calls `schedule`, which is the dataflow loop. Everything
    the loop needs is a method here: `ready_steps` says what may start, `run_step` settles one
    step, `halted` says whether a guard fired or a step failed.
    """

    plan: Plan
    dispatch: Dispatch
    limits: Limits
    env: dict[str, Any]
    settled: dict[str, StepRecord] = field(default_factory=dict[str, StepRecord])
    carried: dict[str, StepRecord] = field(default_factory=dict[str, StepRecord])
    """Parked entries from the prior record, by step name: a fan-out re-dispatches only their parked items."""
    resolutions: dict[str, Any] = field(default_factory=dict[str, Any])
    """The answer a parked step waited for, by step name, passed to `dispatch` when it runs again."""
    suspend_attempts: dict[str, int] = field(default_factory=dict[str, int])
    """Times each step has parked so far, carried from the record; the guard for `max_suspend_attempts`."""
    halt: tuple[RunStatus, str, Any] | None = None
    """`(status, step name, value or error message)` once a guard fired or a step failed."""
    suspensions: dict[str, list[tuple[int | None, Any]]] = field(
        default_factory=dict[str, list[tuple[int | None, Any]]]
    )
    """Parked calls by step name: `(item index or None, payload)`."""

    def __post_init__(self) -> None:
        self.budget = NodeBudget(self.limits.max_expression_nodes)
        self.evaluator = Evaluator(self.budget)
        self.semaphore = asyncio.Semaphore(self.limits.max_concurrency)
        self.order = [s.name for s in self.plan.steps]
        # Data references plus explicit `after` edges: the steps a step waits for.
        self.deps: dict[str, set[str]] = {}
        for step in self.plan.steps:
            deps = step.references() - {'input'}
            if isinstance(step, CallStep):
                deps |= set(step.after)
            self.deps[step.name] = deps

    # -- queries the loop uses ------------------------------------------------------------------

    @property
    def halted(self) -> bool:
        """Whether the run has ended early: a guard fired or a step failed."""
        return self.halt is not None

    @property
    def pending(self) -> list[Step]:
        """Steps not yet settled, in plan order."""
        return [s for s in self.plan.steps if s.name not in self.settled]

    def ready_steps(self) -> list[Step]:
        """Pending steps whose dependencies have all settled and that no unsettled guard fences.

        A guard is a fence: it is ready only once every earlier step has settled, and no step
        after a pending guard is ready. A parked step is settled but bound to nothing, so what
        reads it, and any guard after it, waits for the resolution.
        """
        ready: list[Step] = []
        for step in self.plan.steps:
            if step.name in self.settled:
                continue
            if isinstance(step, GuardStep):
                earlier = self.order[: self.order.index(step.name)]
                if all(self.bound(n) for n in earlier):
                    ready.append(step)
                break  # nothing past an unsettled guard may start
            if all(self.bound(dep) for dep in self.deps[step.name]):
                ready.append(step)
        return ready

    def bound(self, name: str) -> bool:
        """Whether `name` settled with a value a later step may read; a parked step binds nothing."""
        entry = self.settled.get(name)
        return entry is not None and entry.status != 'suspended'

    # -- settling one step ------------------------------------------------------------------------

    async def run_step(self, step: Step) -> None:
        """Evaluate or dispatch `step` and record how it settled. Sets `halt` on a guard or failure."""
        try:
            if isinstance(step, GuardStep):
                if self.eval(step.condition):
                    self.halt = ('returned', step.name, self.eval(step.value))
                    self.settle(step, 'returned')
                else:
                    self.settle(step, 'done')
            elif isinstance(step, DeriveStep):
                self.settle(step, 'done', self.eval(step.expr))
            else:
                await self.run_call(step)
        except EvalError as e:
            self.fail(step, str(e))

    async def run_call(self, step: CallStep) -> None:
        # The resolution reaches only what the record parked: a call the plan re-enters unchanged.
        resolution = self.resolutions.get(step.name) if step.name in self.carried else None
        try:
            if step.each is None:
                value = await self.call_once(step, self.eval_args(step, self.env), resolution)
            else:
                items = _as_list(self.eval(step.each))
                if items is None:
                    raise EvalError(f'fan-out over `{step.each}` needs a list')
                if step.max_items is not None and len(items) > step.max_items:
                    raise EvalError(
                        f'fan-out over `{step.each}` has {len(items)} items, more than its bound of {step.max_items}'
                    )
                assert step.each_var is not None
                scopes: list[dict[str, Any]] = [{**self.env, step.each_var: item} for item in items]
                args = [self.eval_args(step, scope) for scope in scopes]
                value = self.collect_items(step, await self.gather_items(step, args, resolution))
        except Suspend as e:
            self.park(step, [(None, e.payload)])
            return
        except _ItemsParked as e:
            self.park(step, e.parked, e.items)
            return
        except CallError as e:
            self.recover(step, e)
            return
        self.settle(step, 'done', value)

    def recover(self, step: CallStep, error: CallError) -> None:
        """Settle a failed call the way the script asked: error branch, skip, or fail the run."""
        if step.fallback is not None:
            scope = dict(self.env)
            if step.error_var is not None:
                scope[step.error_var] = str(error)
            self.settle(step, 'done', self.evaluator.eval(parse_expression(step.fallback), scope))
        elif step.on_error == 'skip':
            self.settle(step, 'skipped')
        else:
            self.fail(step, str(error))

    async def gather_items(self, step: CallStep, args: Sequence[dict[str, Any]], resolution: Any) -> list[Any]:
        """Call every item, or on a re-entered fan-out only the parked ones; the rest come from the record.

        A settled item comes back as its value, or as the `CallError` it failed with, so
        `collect_items` treats reused and fresh items alike. The carried items apply only when
        they line up with the list being fanned out; otherwise every item runs, unresolved.
        """
        prior = self.carried.get(step.name)
        if prior is None or prior.items is None or len(prior.items) != len(args):
            return await asyncio.gather(*(self.call_once(step, a) for a in args), return_exceptions=True)
        results: list[Any] = []
        fresh: list[int] = []
        for index, item in enumerate(prior.items):
            if item.status == 'suspended':
                results.append(None)
                fresh.append(index)
            elif item.status == 'skipped':
                results.append(CallError(item.error or ''))
            else:
                results.append(item.value)
        calls = [self.call_once(step, args[i], resolution) for i in fresh]
        for index, result in zip(fresh, await asyncio.gather(*calls, return_exceptions=True), strict=True):
            results[index] = result
        return results

    def collect_items(self, step: CallStep, results: list[Any]) -> list[Any]:
        """Turn a fan-out's gathered results into the step value, once every item has settled.

        Gathering with `return_exceptions` is what lets every item finish: without it the first
        failure would settle the step while its siblings kept calling tools that nothing awaited.
        A signal that must escape (deferral, bug) wins over a `CallError`, and a `CallError`
        without `_on_error='skip'` wins over a parked item. With `skip` a failed item settles to
        `None` and the others keep their values. A parked item parks the step with every item's
        outcome recorded, so a resume re-dispatches only the parked ones.
        """
        failures = [r for r in results if isinstance(r, BaseException) and not isinstance(r, Suspend)]
        for failure in failures:
            if not isinstance(failure, CallError):
                raise failure
        if failures and step.on_error != 'skip':
            raise failures[0]  # an error wins over a parked sibling
        parked: list[tuple[int | None, Any]] = [(i, r.payload) for i, r in enumerate(results) if isinstance(r, Suspend)]
        if parked:
            items = [
                ItemRecord('suspended')
                if isinstance(r, Suspend)
                else ItemRecord('skipped', error=str(r))
                if isinstance(r, BaseException)
                else ItemRecord('done', r)
                for r in results
            ]
            raise _ItemsParked(parked, items)
        return [None if isinstance(r, BaseException) else r for r in results]

    async def call_once(self, step: CallStep, args: dict[str, Any], resolution: Any = None) -> Any:
        async with self.semaphore:
            result = await self.dispatch(step, args, resolution=resolution)
        size = len(json.dumps(result, default=str))
        if size > self.limits.max_result_bytes:
            raise CallError(
                f'result of `{step.tool}` is {size} bytes, more than the limit of {self.limits.max_result_bytes}'
            )
        return result

    def eval_args(self, step: CallStep, scope: dict[str, Any]) -> dict[str, Any]:
        return {name: self.evaluator.eval(parse_expression(source), scope) for name, source in step.args.items()}

    def eval(self, source: str) -> Any:
        return self.evaluator.eval(parse_expression(source), self.env)

    def settle(self, step: Step, status: str, value: Any = None, error: str | None = None) -> None:
        assert status in ('done', 'skipped', 'error', 'returned', 'suspended')
        if holds_function_value(value):
            # A record must hold data: it is stored, reused, and returned to the model.
            raise EvalError(f'`{step.name}` holds a function, not a value; write the lambda inline where it is used')
        self.settled[step.name] = StepRecord(hash=step_hash(step), status=status, value=value, error=error)  # pyright: ignore[reportArgumentType]
        if status in ('done', 'skipped'):
            self.env[step.name] = value

    def park(self, step: CallStep, parked: list[tuple[int | None, Any]], items: list[ItemRecord] | None = None) -> None:
        """Settle `step` as parked, unless it has parked `max_suspend_attempts` times already; then it fails."""
        attempts = self.suspend_attempts.get(step.name, 0) + 1
        if attempts > self.limits.max_suspend_attempts:
            self.recover(
                step,
                CallError(
                    f'`{step.tool}` asked for a resolution {attempts} times, more than the limit of '
                    f'{self.limits.max_suspend_attempts}'
                ),
            )
            return
        self.suspend_attempts[step.name] = attempts
        self.suspensions[step.name] = parked
        self.settle(step, 'suspended')
        self.settled[step.name].items = items

    def fail(self, step: Step, message: str) -> None:
        self.settle(step, 'error', error=message)
        if self.halt is None:
            self.halt = ('error', step.name, message)

    # -- the loop ---------------------------------------------------------------------------------

    async def schedule(self) -> None:
        """Drive every pending step to settled, or stop at the first guard that fires or step that fails.

        Event-driven: keep the steps in flight as tasks, wait for any one to settle, then start
        whatever that settlement made ready. A step never waits on an unrelated slow call.

        - Only `ready_steps()` may start. It already encodes data edges, `after` edges, and
          guard fences; the loop just skips steps that are already in flight.
        - `run_step` sets `self.halt` for script-level failures and raises only for signals
          that must escape (approval, deferral) or bugs. Those propagate after the other
          in-flight tasks are cancelled, so no orphan task outlives the run.
        - A halt stops new launches but lets in-flight steps settle, so the record holds what
          their tools actually did. Cancelling them would leave a call half-done on the tool's
          side with no trace in the record.
        - A parked step is settled but binds nothing, so its dependents never become ready.
          Nothing ready, steps pending, nothing in flight is then the run parking, not a
          deadlock; without a parked step it is a bug validation should have caught, so raise
          `PlanExecutionError` rather than return a partial record.
        """
        in_flight: dict[asyncio.Task[None], str] = {}
        try:
            while True:
                if not self.halted:
                    running = set(in_flight.values())
                    for step in self.ready_steps():
                        if step.name not in running:
                            in_flight[asyncio.create_task(self.run_step(step))] = step.name
                if not in_flight:
                    if self.pending and not self.halted and not self.suspensions:
                        names = [s.name for s in self.pending]
                        raise PlanExecutionError(f'no step is ready but {names} are pending')
                    return
                done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    del in_flight[task]
                    task.result()  # re-raise anything run_step let through
        finally:
            for task in in_flight:
                task.cancel()
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)


async def execute_plan(
    plan: Plan,
    *,
    dispatch: Dispatch,
    limits: Limits | None = None,
    record: Record | None = None,
    input: Any = None,
    resolutions: dict[str, Any] | None = None,
) -> ExecuteResult:
    """Execute `plan`, reusing settled steps from `record`, and return the outcome with a new record.

    A step the record holds as `suspended` runs again; `resolutions` maps such a step's name to the
    answer it waited for, handed to `dispatch` as `resolution`.
    """
    limits = limits or Limits()
    reused = reusable_steps(plan, record)
    env: dict[str, Any] = {'input': input}
    env.update({name: entry.value for name, entry in reused.items()})
    runner = Runner(
        plan=plan,
        dispatch=dispatch,
        limits=limits,
        env=env,
        settled=dict(reused),
        carried=parked_steps(plan, record),
        resolutions=dict(resolutions or {}),
        suspend_attempts=dict(record.suspend_attempts) if record is not None else {},
    )
    await runner.schedule()

    status: RunStatus = 'done'
    at: str | None = None
    error: str | None = None
    output: Any = None
    suspensions: list[Suspension] = []
    if runner.halt is not None:
        status, at, payload = runner.halt
        if status == 'returned':
            output = payload
        else:
            error = payload
    elif runner.suspensions:
        status = 'suspended'
        for name in runner.order:
            for index, payload in runner.suspensions.get(name, ()):
                suspensions.append((name, index, payload))
        at = suspensions[0][0]
    elif plan.output is not None:
        try:
            output = runner.eval(plan.output)
            if holds_function_value(output):
                raise EvalError('the result holds a function, not a value')
        except EvalError as e:
            status, at, error = 'error', 'return', str(e)
    elif plan.steps:
        output = runner.env.get(plan.steps[-1].name)

    steps = dict(record.steps) if record is not None else {}
    steps.update(runner.settled)
    attempts = {name: n for name, n in runner.suspend_attempts.items() if steps[name].status == 'suspended'}
    new_record = Record(steps=steps, status=status, at=at, output=output, suspend_attempts=attempts)
    return ExecuteResult(status=status, output=output, record=new_record, at=at, error=error, suspensions=suspensions)
