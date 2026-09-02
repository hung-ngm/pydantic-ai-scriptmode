from __future__ import annotations

import pytest

from pydantic_ai_scriptmode._compile import CompileError, compile_script
from pydantic_ai_scriptmode._plan import CallStep, DeriveStep, GuardStep, step_hash

SCRIPT = """
# Close stale issues and report how many
issues = await list_issues(repo='api', _reason='find stale issues')
stale = [i for i in issues if i['stale']]
if len(stale) == 0:
    return {'closed': 0}
closed = [await close_issue(repo='api', number=i.number) for i in stale[:20] if i.number > 0]
summary = await post_summary(text=f'closed {len(closed)}', _on_error='skip')
return {'closed': len(closed), 'summary': summary}
"""


def kinds(source: str) -> list[str]:
    with pytest.raises(CompileError) as exc:
        compile_script(source)
    return [i.kind for i in exc.value.issues]


class TestGrammar:
    def test_full_script(self):
        plan = compile_script(SCRIPT)
        assert plan.intent == 'Close stale issues and report how many'
        assert plan.output == "{'closed': len(closed), 'summary': summary}"
        assert [type(s).__name__ for s in plan.steps] == ['CallStep', 'DeriveStep', 'GuardStep', 'CallStep', 'CallStep']
        issues, stale, guard, closed, summary = plan.steps
        assert issues == CallStep(
            name='issues', tool='list_issues', args={'repo': "'api'"}, reason='find stale issues', line=3
        )
        assert stale == DeriveStep(name='stale', expr="[i for i in issues if i['stale']]", line=4)
        assert guard == GuardStep(name='_guard3', condition='len(stale) == 0', value="{'closed': 0}", line=5)
        assert isinstance(closed, CallStep)
        assert closed.each == '[i for i in stale[:20] if i.number > 0]'
        assert closed.each_var == 'i'
        assert closed.max_items == 20
        assert closed.args == {'repo': "'api'", 'number': 'i.number'}
        assert closed.after == ('issues',)
        assert isinstance(summary, CallStep)
        assert summary.on_error == 'skip'
        assert summary.after == ('closed',)

    def test_docstring_intent_and_last_value_output(self):
        plan = compile_script('"""Fetch one thing."""\nx = await fetch(url="u")\n')
        assert plan.intent == 'Fetch one thing.'
        assert plan.output is None

    def test_gather_makes_concurrent_calls(self):
        plan = compile_script('a, b = await asyncio.gather(fetch(url="a"), fetch(url="b"))\nc = await fetch(url=a)')
        a, b, c = plan.steps
        assert isinstance(a, CallStep) and isinstance(b, CallStep) and isinstance(c, CallStep)
        assert a.after == () and b.after == ()
        assert c.after == ('a', 'b')

    def test_for_loop_with_bare_call_is_anonymous_fanout(self):
        plan = compile_script('for i in xs[2:5]:\n    await close(number=i)')
        (step,) = plan.steps
        assert isinstance(step, CallStep)
        assert step.name == '_call1' and step.each == 'xs[2:5]' and step.max_items == 3

    def test_list_display_bounds_fanout(self):
        plan = compile_script('r = [await f(x=i) for i in [1, 2, 3]]')
        (step,) = plan.steps
        assert isinstance(step, CallStep) and step.max_items == 3

    def test_try_except_becomes_error_branch(self):
        plan = compile_script("try:\n    x = await fetch(url='u')\nexcept Exception as e:\n    x = {'error': str(e)}")
        (step,) = plan.steps
        assert isinstance(step, CallStep)
        assert step.fallback == "{'error': str(e)}" and step.error_var == 'e'

    def test_try_except_pass_skips(self):
        plan = compile_script('try:\n    await notify(msg="m")\nexcept Exception:\n    pass')
        (step,) = plan.steps
        assert isinstance(step, CallStep) and step.fallback == 'None' and step.error_var is None

    def test_anonymous_call_and_return_none(self):
        plan = compile_script('await notify(msg="m")\nreturn')
        assert plan.steps[0].name == '_call1'
        assert plan.output == 'None'

    def test_hash_ignores_reason_and_line(self):
        a = compile_script("x = await f(k=1, _reason='a')").steps[0]
        b = compile_script("\n\nx = await f(k=1, _reason='b')").steps[0]
        c = compile_script('x = await f(k=2)').steps[0]
        assert step_hash(a) == step_hash(b) != step_hash(c)


class TestRejections:
    @pytest.mark.parametrize(
        'source,expected',
        [
            ('while True:\n    pass', ['while_loop']),
            ('r = [await f(x=i) for i in xs]', ['unbounded_for']),
            ('r = [await f(x=i) for i in xs[:n]]', ['unbounded_for']),
            ('for i in xs[:3]:\n    r = await f(x=i)', ['for_body']),
            ('def g():\n    pass', ['function_def']),
            ('class C:\n    pass', ['class_def']),
            ('import os', ['import_statement']),
            ('x += 1', ['augmented_assignment']),
            ('assert x', ['unsupported_statement']),
            ('x + 1', ['bare_expression']),
            ('a = b = 1', ['multiple_targets']),
            ('x.y = 1', ['multiple_targets']),
            ('return 1\nx = 2', ['return_not_last']),
            ('if x:\n    y = 1', ['guard_shape']),
            ('if x:\n    return 1\nelse:\n    return 2', ['guard_shape']),
            ('try:\n    x = await f()\n    y = 1\nexcept Exception:\n    x = 1', ['try_shape']),
            ('try:\n    x = await f()\nexcept Exception:\n    y = 1', ['try_shape']),
            ('a, b = await asyncio.gather(f(), g(), h())', ['gather_shape']),
            ('x = await f(1)', ['call_positional_args']),
            ('x = f(k=1)', ['call_not_awaited']),
            ('f(k=1)', ['call_not_awaited']),
            ('x = [await f(k=1)]', ['call_nested']),
            ('x = await f(k=1, _retry=2)', ['unknown_call_option']),
            ('x = await f(**kw)', ['unknown_call_option']),
            ("x = await f(_on_error='retry')", ['bad_on_error']),
            ('x = (', ['syntax_error']),
            ('x = y.__dict__', ['dunder_attribute']),
            ('x = xs.append(1)', ['unsupported_method']),
        ],
    )
    def test_kind(self, source: str, expected: list[str]):
        assert kinds(source) == expected

    def test_all_issues_are_reported_together(self):
        assert kinds('while True:\n    pass\nimport os\nx = 2 ** 3') == [
            'while_loop',
            'import_statement',
            'unsupported_expression',
        ]
        with pytest.raises(CompileError) as exc:
            compile_script('while True:\n    pass\nimport os')
        assert [i.line for i in exc.value.issues] == [1, 3]
