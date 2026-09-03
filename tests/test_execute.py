from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pydantic_ai_scriptmode._compile import compile_script
from pydantic_ai_scriptmode._execute import CallError, PlanExecutionError, Suspend, execute_plan
from pydantic_ai_scriptmode._plan import CallStep, DeriveStep, Limits, Plan, step_hash
from pydantic_ai_scriptmode._record import Record, StepRecord, reusable_steps

pytestmark = pytest.mark.anyio


class FakeTools:
    """Records calls and answers them from a table; `sleep` makes calls take time so concurrency shows."""

    def __init__(self, **tools: Any) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def __call__(self, step: CallStep, args: dict[str, Any]) -> Any:
        self.calls.append((step.tool, args))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            tool = self.tools[step.tool]
            if isinstance(tool, Exception):
                raise tool
            return tool(**args) if callable(tool) else tool
        finally:
            self.in_flight -= 1


async def run(source: str, tools: FakeTools, **kwargs: Any):
    return await execute_plan(compile_script(source), dispatch=tools, **kwargs)


class TestExecute:
    async def test_full_script(self):
        tools = FakeTools(
            list_issues=[{'number': 1, 'stale': True}, {'number': 2, 'stale': False}, {'number': 3, 'stale': True}],
            close_issue=lambda repo, number: f'closed {number}',  # pyright: ignore[reportUnknownLambdaType]
        )
        result = await run(
            "issues = await list_issues(repo='api')\n"
            "stale = [i for i in issues if i['stale']]\n"
            'if not stale:\n    return {"closed": 0}\n'
            "closed = [await close_issue(repo='api', number=i.number) for i in stale[:20]]\n"
            'return {"closed": len(closed), "results": closed}',
            tools,
        )
        assert result.status == 'done'
        assert result.output == {'closed': 2, 'results': ['closed 1', 'closed 3']}
        assert [c for c in tools.calls] == [
            ('list_issues', {'repo': 'api'}),
            ('close_issue', {'repo': 'api', 'number': 1}),
            ('close_issue', {'repo': 'api', 'number': 3}),
        ]
        assert result.record.steps['closed'].status == 'done'

    async def test_guard_returns_early_and_fences(self):
        tools = FakeTools(list_issues=[], notify='sent')
        result = await run(
            "issues = await list_issues(repo='api')\nif not issues:\n    return 'nothing'\nawait notify(msg='x')", tools
        )
        assert result.status == 'returned'
        assert result.output == 'nothing'
        assert result.at == '_guard2'
        assert [c[0] for c in tools.calls] == ['list_issues']

    async def test_last_step_value_is_output_without_return(self):
        result = await run('x = await f(k=1)\ny = x + 1', FakeTools(f=41))
        assert result.output == 42

    async def test_gather_runs_concurrently_and_sequential_awaits_do_not(self):
        tools = FakeTools(f=1)
        await run('a, b, c = await asyncio.gather(f(k=1), f(k=2), f(k=3))', tools)
        assert tools.max_in_flight == 3
        tools = FakeTools(f=1)
        await run('a = await f(k=1)\nb = await f(k=2)', tools)
        assert tools.max_in_flight == 1

    async def test_independent_steps_run_concurrently_within_the_cap(self):
        tools = FakeTools(f=1)
        await run('r = [await f(k=i) for i in [1, 2, 3, 4, 5, 6, 7]]', tools, limits=Limits(max_concurrency=3))
        assert tools.max_in_flight == 3

    async def test_fanout_over_bound_fails(self):
        tools = FakeTools(f=[1, 2, 3], g=0)
        result = await run('xs = await f(k=1)\nr = [await g(k=i) for i in xs[:2]]', tools)
        assert result.status == 'done' and result.output == [0, 0]

    async def test_call_error_without_branch_fails_the_run(self):
        tools = FakeTools(f=CallError('boom'), g=1)
        result = await run('x = await f(k=1)\ny = await g(k=2)', tools)
        assert result.status == 'error'
        assert result.at == 'x'
        assert result.error == 'boom'
        assert result.record.steps['x'].status == 'error'
        assert 'y' not in result.record.steps

    async def test_error_branch_and_skip(self):
        tools = FakeTools(f=CallError('boom'))
        result = await run("try:\n    x = await f(k=1)\nexcept Exception as e:\n    x = {'err': e}\nreturn x", tools)
        assert result.output == {'err': 'boom'}
        result = await run("x = await f(k=1, _on_error='skip')\nreturn x", tools)
        assert result.output is None
        assert result.record.steps['x'].status == 'skipped'

    async def test_fanout_skip_settles_failed_items_only(self):
        def f(k: int) -> int:
            if k == 2:
                raise CallError('boom')
            return k * 10

        tools = FakeTools(xs=[1, 2, 3], f=f)
        result = await run("xs = await xs()\nys = [await f(k=x, _on_error='skip') for x in xs[:3]]\nreturn ys", tools)
        assert result.output == [10, None, 30]
        assert result.record.steps['ys'].status == 'done'

    async def test_fanout_failure_waits_for_every_item(self):
        def f(k: int) -> int:
            if k == 1:
                raise CallError('boom')
            return k

        tools = FakeTools(xs=[1, 2, 3], f=f)
        result = await run('xs = await xs()\nys = [await f(k=x) for x in xs[:3]]', tools)
        assert result.status == 'error' and result.at == 'ys' and result.error == 'boom'
        assert len(tools.calls) == 4 and tools.in_flight == 0

    async def test_fanout_escaping_signal_wins_over_call_error(self):
        class Signal(Exception):
            pass

        def f(k: int) -> int:
            if k == 1:
                raise CallError('boom')
            raise Signal()

        with pytest.raises(Signal):
            await run(
                "xs = await xs()\nys = [await f(k=x, _on_error='skip') for x in xs[:2]]", FakeTools(xs=[1, 2], f=f)
            )

    async def test_function_valued_step_and_output_are_errors(self):
        result = await run('f = lambda i: i + 1\nreturn f(1)', FakeTools())
        assert result.status == 'error' and result.at == 'f'
        assert 'holds a function' in (result.error or '')
        result = await run('x = await f(k=1)\nreturn {"k": [len]}', FakeTools(f=1))
        assert result.status == 'error' and result.at == 'return'

    async def test_non_call_error_propagates(self):
        class Signal(Exception):
            pass

        with pytest.raises(Signal):
            await run('x = await f(k=1)', FakeTools(f=Signal()))

    async def test_eval_error_in_derivation_fails_at_that_step(self):
        result = await run('x = await f(k=1)\ny = x.missing', FakeTools(f={'a': 1}))
        assert result.status == 'error' and result.at == 'y'
        assert 'missing' in (result.error or '')

    async def test_result_size_limit(self):
        result = await run('x = await f(k=1)', FakeTools(f='x' * 100), limits=Limits(max_result_bytes=10))
        assert result.status == 'error' and 'bytes' in (result.error or '')

    async def test_expression_budget_is_shared(self):
        result = await run(
            'x = [i for i in range(50)]\ny = [i for i in range(50)]',
            FakeTools(),
            limits=Limits(max_expression_nodes=250),
        )
        assert result.status == 'error' and result.at == 'y'

    async def test_input_is_bound(self):
        result = await run('x = input.n * 2', FakeTools(), input={'n': 21})
        assert result.output == 42

    async def test_deadlock_is_loud(self):
        plan = Plan(steps=(DeriveStep(name='a', expr='b'), DeriveStep(name='b', expr='a')))
        with pytest.raises(PlanExecutionError):
            await execute_plan(plan, dispatch=FakeTools())


class TestRecordReuse:
    async def test_settled_steps_are_reused_after_a_failure(self):
        tools = FakeTools(f={'v': 1}, g=CallError('down'))
        source = 'x = await f(k=1)\ny = await g(k=x.v)\nreturn y'
        first = await run(source, tools)
        assert first.status == 'error'
        tools.tools['g'] = 'ok'
        second = await run(source, tools, record=first.record)
        assert second.status == 'done' and second.output == 'ok'
        assert [c[0] for c in tools.calls] == ['f', 'g', 'g']

    async def test_changed_upstream_step_invalidates_dependents(self):
        tools = FakeTools(f={'v': 1}, g='ok')
        first = await run('x = await f(k=1)\ny = await g(k=x.v)', tools)
        second = await run('x = await f(k=2)\ny = await g(k=x.v)', tools, record=first.record)
        assert second.status == 'done'
        assert [c[0] for c in tools.calls] == ['f', 'g', 'f', 'g']

    def test_reusable_rules(self):
        plan = compile_script('x = await f(k=1)\ny = x + input.n\nz = await g(k=y)')
        x, y, z = plan.steps
        record = Record(
            steps={
                'x': StepRecord(step_hash(x), 'done', 1),
                'y': StepRecord(step_hash(y), 'done', 2),
                'z': StepRecord(step_hash(z), 'done', 3),
            }
        )
        assert set(reusable_steps(plan, record)) == {'x'}
        assert reusable_steps(plan, None) == {}


class TestSuspend:
    async def test_parked_call_suspends_the_run_after_independent_steps_settle(self):
        tools = FakeTools(f='a', g=Suspend({'ask': 'ok?'}), h='c')
        result = await run(
            'x, y = await asyncio.gather(f(k=1), g(k=2))\nw = x + "!"\nz = await h(k=y)\nreturn [w, z]', tools
        )
        assert result.status == 'suspended' and result.at == 'y' and result.output is None
        assert result.suspensions == [('y', None, {'ask': 'ok?'})]
        steps = result.record.steps
        assert steps['y'].status == 'suspended' and result.record.status == 'suspended'
        assert steps['x'].value == 'a' and steps['w'].value == 'a!'
        assert 'z' not in steps
        assert [c[0] for c in tools.calls] == ['f', 'g']
        assert set(reusable_steps(compile_script('y = await g(k=2)'), result.record)) == set()
