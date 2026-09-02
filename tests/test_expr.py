from __future__ import annotations

import pytest

from pydantic_ai_scriptmode._expr import EvalError, ExprError, NodeBudget, evaluate, free_names, parse_expression


def ev(src: str, **env: object) -> object:
    return evaluate(src, env, budget=NodeBudget(10_000))


class TestEvaluate:
    def test_literals_and_containers(self):
        assert ev('[1, "a", None, True, {"k": 2.5}, (1, 2)]') == [1, 'a', None, True, {'k': 2.5}, [1, 2]]

    def test_fstring(self):
        assert ev('f"closed {len(xs)} of {n!r}"', xs=[1, 2], n='x') == "closed 2 of 'x'"

    def test_arithmetic_and_comparison(self):
        assert ev('(a + b) * 2 - 1 // 1 % 5', a=1, b=2) == 5
        assert ev('1 < a <= 2 and not b or c in [3]', a=2, b=False, c=3) is True

    def test_subscript_slice_and_attribute_on_dict(self):
        issues = [{'number': i, 'stale': i % 2 == 0} for i in range(5)]
        assert ev('issues[1:3]', issues=issues) == issues[1:3]
        assert ev('issues[0].number', issues=issues) == 0
        assert ev('issues[-1]["stale"]', issues=issues) is True

    def test_comprehensions_with_filters_and_lambda(self):
        issues = [{'n': 3}, {'n': 1}, {'n': 2}]
        assert ev('[i.n for i in issues if i.n > 1]', issues=issues) == [3, 2]
        assert ev('{i.n: i for i in issues}', issues=issues) == {3: {'n': 3}, 1: {'n': 1}, 2: {'n': 2}}
        assert ev('sorted(issues, key=lambda i: i.n)', issues=issues) == [{'n': 1}, {'n': 2}, {'n': 3}]
        assert ev('sum(i.n for i in issues)', issues=issues) == 6

    def test_builtins_and_json(self):
        assert ev('list(zip(range(2), reversed([1, 2])))') == [[0, 2], [1, 1]]
        assert ev('json.loads(json.dumps({"a": 1}))') == {'a': 1}
        assert ev('max([1, 5, 2])') == 5

    def test_str_and_dict_methods(self):
        assert ev('", ".join(s.upper() for s in xs)', xs=['a', 'b']) == 'A, B'
        assert ev('d.get("missing", 0) + len(d.keys())', d={'a': 1}) == 1

    def test_ternary_short_circuits(self):
        assert ev('a if a else b', a=0, b='fallback') == 'fallback'

    def test_missing_key_is_eval_error(self):
        with pytest.raises(EvalError, match='no key `nope`'):
            ev('d.nope', d={'a': 1})

    def test_undefined_name_is_eval_error(self):
        with pytest.raises(EvalError, match='not defined'):
            ev('missing + 1')

    def test_budget_bounds_comprehensions(self):
        with pytest.raises(EvalError, match='budget'):
            evaluate('[i for i in range(1000)]', {}, budget=NodeBudget(100))

    def test_mutating_method_is_refused(self):
        with pytest.raises(ExprError) as exc:
            parse_expression('xs.append(1)')
        assert exc.value.kind == 'unsupported_method'


class TestParse:
    @pytest.mark.parametrize(
        'source,kind',
        [
            ('x.__class__', 'dunder_attribute'),
            ('2 ** 10', 'unsupported_expression'),
            ('await fetch(url=u)', 'call_nested'),
            ('json.dump(x)', 'unknown_function'),
            ('(yield)', 'unsupported_expression'),
        ],
    )
    def test_rejections(self, source: str, kind: str):
        with pytest.raises(ExprError) as exc:
            parse_expression(source)
        assert exc.value.kind == kind

    def test_syntax_error(self):
        with pytest.raises(ExprError) as exc:
            parse_expression('1 +')
        assert exc.value.kind == 'syntax_error'


class TestFreeNames:
    def test_excludes_bound_and_builtin_names(self):
        assert free_names(parse_expression('[len(i.n) for i in xs if i.n > k]')) == {'xs', 'k'}
        assert free_names(parse_expression('sorted(xs, key=lambda i: i.n + y)')) == {'xs', 'y'}
        assert free_names(parse_expression('json.dumps(input)')) == {'input'}
