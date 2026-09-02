from __future__ import annotations

from pydantic_ai_scriptmode._compile import compile_script
from pydantic_ai_scriptmode._plan import CallStep, Limits, Plan
from pydantic_ai_scriptmode._validate import ToolSignature, validate_plan

TOOLS = {
    'list_issues': ToolSignature('list_issues', frozenset({'repo', 'state'}), frozenset({'repo'})),
    'close_issue': ToolSignature('close_issue', frozenset({'repo', 'number'}), frozenset({'repo', 'number'})),
}


def kinds(source: str, limits: Limits | None = None) -> list[str]:
    return [i.kind for i in validate_plan(compile_script(source), tools=TOOLS, limits=limits or Limits())]


class TestValidate:
    def test_valid_script_has_no_issues(self):
        source = (
            "issues = await list_issues(repo='api')\n"
            "stale = [i for i in issues if i['stale']]\n"
            'if not stale:\n    return 0\n'
            "closed = [await close_issue(repo='api', number=i.number) for i in stale[:20]]\n"
            'return len(closed)'
        )
        assert kinds(source) == []

    def test_unknown_tool_and_arguments(self):
        assert kinds(
            "x = await nope(a=1)\ny = await list_issues(repo='r', page=2)\nz = await close_issue(repo='r')"
        ) == [
            'unknown_tool',
            'unknown_argument',
            'missing_argument',
        ]

    def test_names(self):
        assert kinds("x = await list_issues(repo=later)\nlater = 'r'") == ['forward_reference']
        assert kinds('x = missing + 1') == ['undefined_name']
        assert kinds("len = await list_issues(repo='r')") == ['reserved_name']
        assert kinds("x = await list_issues(repo='r')\nx = 1") == ['duplicate_step']
        assert kinds('xs = [1]\nx = [g(i) for i in xs]') == ['unknown_function']
        assert kinds("x = await list_issues(repo='r')\nreturn missing") == ['undefined_name']

    def test_step_lambda_may_be_called(self):
        assert kinds('f = lambda i: i * 2\nx = f(2)') == []

    def test_fanout_variable_is_not_undefined(self):
        assert kinds("r = [await close_issue(repo='r', number=i) for i in [1, 2]]") == []
        assert kinds("try:\n    x = await list_issues(repo='r')\nexcept Exception as e:\n    x = str(e)") == []

    def test_limits(self):
        many = '\n'.join(f"s{i} = await list_issues(repo='r')" for i in range(3))
        assert kinds(many, Limits(max_steps=2)) == ['too_many_steps']
        assert kinds(
            "r = [await close_issue(repo='r', number=i) for i in xs[:50]]\nxs = []", Limits(max_items_per_fanout=10)
        ) == [
            'forward_reference',
            'fanout_too_large',
        ]
        assert kinds(
            "a = await list_issues(repo='r')\nr = [await close_issue(repo='r', number=i) for i in a[:5]]",
            Limits(max_total_calls=5),
        ) == ['too_many_calls']

    def test_input_is_always_bound(self):
        assert kinds('x = input.value') == []

    def test_hand_built_fanout_needs_a_bound(self):
        step = CallStep(name='x', tool='close_issue', args={'repo': "'r'", 'number': 'i'}, each='[1, 2]', each_var='i')
        plan = Plan(intent='t', steps=(step,))
        assert [i.kind for i in validate_plan(plan, tools=TOOLS, limits=Limits())] == ['unbounded_for']
