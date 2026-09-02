"""The expression subset: parse, list free names, and evaluate with a node budget.

An expression is a pure fragment of the authoring language: it reads earlier step values and
computes a new value, and can neither call a tool nor mutate anything. The parser accepts a fixed
set of `ast` node types; the evaluator is a tree walk over those nodes with a budget so a
comprehension over a large list cannot run unbounded. No `eval`, no `exec`, no `compile`.
"""

from __future__ import annotations

import ast
import json
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai_scriptmode._teaching import RejectionKind, explain


def _reversed(xs: Any) -> list[Any]:
    return list(reversed(xs))


def _enumerate(xs: Any, start: int = 0) -> list[Any]:
    return [[i, x] for i, x in enumerate(xs, start)]


def _zip(*xs: Any) -> list[Any]:
    return [list(t) for t in zip(*xs)]


def _set(xs: Any = ()) -> list[Any]:
    return sorted(set(xs))


def _range(*args: Any) -> range:
    return range(*args)


# Names a script may call as plain functions. Every entry returns a plain value (iterators are
# materialized) so step values stay JSON-shaped.
BUILTIN_FUNCTIONS: dict[str, Callable[..., Any]] = {
    'len': len,
    'sum': sum,
    'min': min,
    'max': max,
    'sorted': sorted,
    'reversed': _reversed,
    'enumerate': _enumerate,
    'zip': _zip,
    'any': any,
    'all': all,
    'abs': abs,
    'round': round,
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
    'list': list,
    'dict': dict,
    'set': _set,
    'range': _range,  # materialized and charged to the budget in `_call_builtin`
}

# `json` is the only module a script may name; `asyncio` is recognised by the compiler only.
MODULE_FUNCTIONS: dict[str, dict[str, Callable[..., Any]]] = {
    'json': {'dumps': json.dumps, 'loads': json.loads},
}

# Non-mutating methods, keyed by receiver type. Anything else on these types is refused.
_STR_METHODS = frozenset(
    [
        'upper',
        'lower',
        'strip',
        'lstrip',
        'rstrip',
        'split',
        'rsplit',
        'join',
        'replace',
        'startswith',
        'endswith',
        'find',
        'rfind',
        'count',
        'format',
        'title',
        'capitalize',
        'isdigit',
        'isalpha',
        'isalnum',
        'isupper',
        'islower',
        'isspace',
        'splitlines',
        'partition',
        'rpartition',
        'zfill',
        'removeprefix',
        'removesuffix',
        'casefold',
        'swapcase',
        'index',
    ]
)
_LIST_METHODS = frozenset({'index', 'count'})
_DICT_METHODS = frozenset({'get', 'keys', 'values', 'items'})

# Names bound by the engine, never by a step.
RESERVED_NAMES = frozenset({*BUILTIN_FUNCTIONS, *MODULE_FUNCTIONS, 'input', 'asyncio', 'True', 'False', 'None'})

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: operator.mod,
}
_COMPARE_OPERATORS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_EXPRESSION_NODES: tuple[type[ast.AST], ...] = (
    ast.Constant,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Name,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.IfExp,
    ast.Lambda,
    ast.ListComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Call,
    ast.keyword,
    ast.comprehension,
    ast.arguments,
    ast.arg,
    ast.Load,
    ast.Store,
    *_BINARY_OPERATORS,
    *_COMPARE_OPERATORS,
    *_UNARY_OPERATORS,
    ast.And,
    ast.Or,
)


class ExprError(Exception):
    """An expression the language does not accept. Raised at parse time, before anything runs."""

    def __init__(self, kind: RejectionKind, **details: object) -> None:
        self.kind: RejectionKind = kind
        self.details = details
        super().__init__(explain(kind, **details))


class EvalError(Exception):
    """An expression that failed while evaluating: a missing key, a type mismatch, a spent budget."""


@dataclass
class NodeBudget:
    """Counts evaluated nodes so an expression's work is bounded by `limit`."""

    limit: int
    spent: int = 0

    def spend(self, n: int = 1) -> None:
        """Charge `n` nodes; raise `EvalError` once the budget is exhausted."""
        self.spent += n
        if self.spent > self.limit:
            raise EvalError(f'expression exceeded the budget of {self.limit} evaluation steps')


def parse_expression(source: str) -> ast.expr:
    """Parse `source` as one expression and check every node is in the subset."""
    try:
        tree = ast.parse(source, mode='eval')
    except SyntaxError as e:
        raise ExprError('syntax_error', message=e.msg) from e
    check_expression(tree.body)
    return tree.body


def check_expression(node: ast.expr) -> None:
    """Reject any node outside the subset. Structural only; names are checked by the validator."""
    for child in ast.walk(node):
        if isinstance(child, ast.Await):
            raise ExprError('call_nested', tool=_call_name(child.value))
        if not isinstance(child, _EXPRESSION_NODES):
            raise ExprError('unsupported_expression', node=type(child).__name__)
        if isinstance(child, ast.Attribute) and child.attr.startswith('_'):
            raise ExprError('dunder_attribute', name=child.attr)
        if isinstance(child, ast.Call):
            _check_call(child)
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow):
            raise ExprError('unsupported_expression', node='Pow')
        if isinstance(child, ast.Lambda) and (child.args.vararg or child.args.kwarg or child.args.kwonlyargs):
            raise ExprError('unsupported_expression', node='Lambda')


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return ast.unparse(node.func)
    return ast.unparse(node)


def _check_call(node: ast.Call) -> None:
    func = node.func
    if isinstance(func, ast.Name):
        # A name that is not a builtin may be a lambda bound by a step, a comprehension, or an
        # outer lambda; only the validator has the scope to tell, so it owns `unknown_function`.
        return
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id in MODULE_FUNCTIONS:
            if func.attr not in MODULE_FUNCTIONS[func.value.id]:
                raise ExprError('unknown_function', name=f'{func.value.id}.{func.attr}')
            return
        if func.attr not in (_STR_METHODS | _LIST_METHODS | _DICT_METHODS):
            raise ExprError('unsupported_method', name=func.attr)
        return
    raise ExprError('unsupported_expression', node=type(func).__name__)


def free_names(node: ast.expr) -> set[str]:
    """Names the expression reads that nothing inside it binds, excluding builtins and modules.

    These are the step names the expression depends on (plus `input`), so they define the
    dataflow edges of the plan.
    """
    found: set[str] = set()
    _collect_free(node, frozenset(), found)
    return {n for n in found if n not in BUILTIN_FUNCTIONS and n not in MODULE_FUNCTIONS}


def _collect_free(node: ast.AST, bound: frozenset[str], found: set[str]) -> None:
    if isinstance(node, ast.Name):
        if node.id not in bound:
            found.add(node.id)
        return
    if isinstance(node, ast.Lambda):
        inner = bound | {a.arg for a in node.args.args}
        for default in node.args.defaults:
            _collect_free(default, bound, found)
        _collect_free(node.body, inner, found)
        return
    if isinstance(node, (ast.ListComp, ast.DictComp, ast.GeneratorExp)):
        inner = bound
        for gen in node.generators:
            # The first iterable is evaluated in the enclosing scope; later ones see earlier targets.
            _collect_free(gen.iter, inner, found)
            inner = inner | _target_names(gen.target)
            for cond in gen.ifs:
                _collect_free(cond, inner, found)
        if isinstance(node, ast.DictComp):
            _collect_free(node.key, inner, found)
            _collect_free(node.value, inner, found)
        else:
            _collect_free(node.elt, inner, found)
        return
    for child in ast.iter_child_nodes(node):
        _collect_free(child, bound, found)


def _target_names(target: ast.expr) -> frozenset[str]:
    if isinstance(target, ast.Name):
        return frozenset({target.id})
    if isinstance(target, ast.Tuple):
        names: frozenset[str] = frozenset()
        for e in target.elts:
            names |= _target_names(e)
        return names
    raise ExprError('unsupported_expression', node=type(target).__name__)


@dataclass
class _Closure:
    """A lambda value: parameters, body, and the environment it closed over."""

    params: list[str]
    body: ast.expr
    env: Mapping[str, Any]
    evaluator: Evaluator
    defaults: list[Any] = field(default_factory=list[Any])

    def __call__(self, *args: Any) -> Any:
        if len(args) > len(self.params) or len(args) + len(self.defaults) < len(self.params):
            raise EvalError(f'lambda takes {len(self.params)} argument(s), got {len(args)}')
        bound = dict(self.env)
        values = [*args, *self.defaults[len(args) - (len(self.params) - len(self.defaults)) :]]
        bound.update(zip(self.params, values))
        return self.evaluator.eval(self.body, bound)


@dataclass
class Evaluator:
    """Tree-walking interpreter over a parsed expression, bounded by a shared `NodeBudget`."""

    budget: NodeBudget

    def eval(self, node: ast.expr, env: Mapping[str, Any]) -> Any:
        """Evaluate `node` in `env`; every node costs one budget unit."""
        self.budget.spend()
        try:
            return self._eval(node, env)
        except EvalError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, ZeroDivisionError) as e:
            raise EvalError(f'{type(e).__name__}: {e} in `{ast.unparse(node)}`') from e

    def _eval(self, node: ast.expr, env: Mapping[str, Any]) -> Any:  # noqa: C901
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in BUILTIN_FUNCTIONS:
                return _Builtin(node.id, self)
            raise EvalError(f'name `{node.id}` is not defined')
        if isinstance(node, ast.JoinedStr):
            return ''.join(str(self.eval(v, env)) for v in node.values)
        if isinstance(node, ast.FormattedValue):
            value = self.eval(node.value, env)
            if node.conversion == ord('r'):
                value = repr(value)
            elif node.conversion == ord('s'):
                value = str(value)
            spec = self.eval(node.format_spec, env) if node.format_spec is not None else ''
            return format(value, spec)
        if isinstance(node, ast.List):
            return [self.eval(e, env) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return [self.eval(e, env) for e in node.elts]
        if isinstance(node, ast.Dict):
            out: dict[Any, Any] = {}
            for k, v in zip(node.keys, node.values):
                if k is None:
                    out.update(self.eval(v, env))
                else:
                    out[self.eval(k, env)] = self.eval(v, env)
            return out
        if isinstance(node, ast.Subscript):
            return self._subscript(self.eval(node.value, env), node.slice, env)
        if isinstance(node, ast.Attribute):
            return self._attribute(self.eval(node.value, env), node.attr)
        if isinstance(node, ast.Compare):
            left = self.eval(node.left, env)
            for op, comparator in zip(node.ops, node.comparators):
                right = self.eval(comparator, env)
                if not _COMPARE_OPERATORS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            result: Any = None
            want_truthy = isinstance(node.op, ast.Or)
            for v in node.values:
                result = self.eval(v, env)
                if bool(result) == want_truthy:
                    return result
            return result
        if isinstance(node, ast.BinOp):
            return _BINARY_OPERATORS[type(node.op)](self.eval(node.left, env), self.eval(node.right, env))
        if isinstance(node, ast.UnaryOp):
            return _UNARY_OPERATORS[type(node.op)](self.eval(node.operand, env))
        if isinstance(node, ast.IfExp):
            return self.eval(node.body, env) if self.eval(node.test, env) else self.eval(node.orelse, env)
        if isinstance(node, ast.Lambda):
            return _Closure(
                params=[a.arg for a in node.args.args],
                body=node.body,
                env=env,
                evaluator=self,
                defaults=[self.eval(d, env) for d in node.args.defaults],
            )
        if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
            return [self.eval(node.elt, scope) for scope in self._comprehension_scopes(node.generators, env)]
        if isinstance(node, ast.DictComp):
            return {
                self.eval(node.key, scope): self.eval(node.value, scope)
                for scope in self._comprehension_scopes(node.generators, env)
            }
        if isinstance(node, ast.Call):
            return self._call(node, env)
        raise EvalError(f'unsupported expression node {type(node).__name__}')  # pragma: no cover

    def _subscript(self, value: Any, index: ast.expr, env: Mapping[str, Any]) -> Any:
        if isinstance(index, ast.Slice):
            lower = self.eval(index.lower, env) if index.lower is not None else None
            upper = self.eval(index.upper, env) if index.upper is not None else None
            step = self.eval(index.step, env) if index.step is not None else None
            return value[lower:upper:step]
        return value[self.eval(index, env)]

    @staticmethod
    def _attribute(value: Any, attr: str) -> Any:
        # `isinstance` narrows `value` to an unparameterized generic, which reads as partially
        # unknown under strict typing; `raw` keeps the unnarrowed alias for the actual access.
        raw: Any = value
        type_name = type(raw).__name__
        if isinstance(value, dict):
            if attr in value:
                return raw[attr]
            keys: list[str] = sorted(str(k) for k in raw)
            raise EvalError(f'no key `{attr}` in {keys}')
        if (isinstance(value, str) and attr in _STR_METHODS) or (isinstance(value, list) and attr in _LIST_METHODS):
            return getattr(raw, attr)
        raise EvalError(f'`{type_name}` has no attribute `{attr}`')

    def _comprehension_scopes(
        self, generators: list[ast.comprehension], env: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        scopes: list[dict[str, Any]] = [dict(env)]
        for gen in generators:
            next_scopes: list[dict[str, Any]] = []
            for scope in scopes:
                for item in self.eval(gen.iter, scope):
                    self.budget.spend()
                    inner = dict(scope)
                    _bind_target(gen.target, item, inner)
                    if all(self.eval(cond, inner) for cond in gen.ifs):
                        next_scopes.append(inner)
            scopes = next_scopes
        return scopes

    def _call(self, node: ast.Call, env: Mapping[str, Any]) -> Any:
        args = [self.eval(a, env) for a in node.args]
        kwargs = {kw.arg: self.eval(kw.value, env) for kw in node.keywords if kw.arg is not None}
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in env:
                target = env[func.id]
                if not isinstance(target, _Closure):
                    raise EvalError(f'`{func.id}` is not callable')
                return target(*args)
            if func.id in BUILTIN_FUNCTIONS:
                return self._call_builtin(func.id, args, kwargs)
            raise EvalError(f'name `{func.id}` is not defined')
        assert isinstance(func, ast.Attribute)
        if isinstance(func.value, ast.Name) and func.value.id in MODULE_FUNCTIONS and func.value.id not in env:
            return MODULE_FUNCTIONS[func.value.id][func.attr](*args, **kwargs)
        receiver = self.eval(func.value, env)
        return self._call_method(receiver, func.attr, args, kwargs)

    def _call_builtin(self, name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if name == 'range':
            r = range(*args)
            self.budget.spend(len(r))
            return list(r)
        if name in (
            'sorted',
            'min',
            'max',
            'sum',
            'any',
            'all',
            'len',
            'list',
            'dict',
            'set',
            'reversed',
            'enumerate',
            'zip',
        ):
            # Container builtins walk their input; charge for it so a huge list is not free.
            for a in args:
                if isinstance(a, (list, dict, str)):
                    self.budget.spend(len(a))  # pyright: ignore[reportUnknownArgumentType]
        fn = BUILTIN_FUNCTIONS[name]
        assert fn is not None
        return fn(*args, **kwargs)

    def _call_method(self, receiver: Any, name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        raw: Any = receiver
        type_name = type(raw).__name__
        method: Any = getattr(raw, name, None)
        if isinstance(receiver, str) and name in _STR_METHODS:
            return method(*args, **kwargs)
        if isinstance(receiver, list) and name in _LIST_METHODS:
            return method(*args)
        if isinstance(receiver, dict) and name in _DICT_METHODS:
            if name == 'get':
                return method(*args)
            self.budget.spend(len(raw))
            return list(method())
        raise EvalError(f'`{type_name}` has no method `{name}`')


@dataclass
class _Builtin:
    """A builtin referenced as a value (for example `key=len`)."""

    name: str
    evaluator: Evaluator

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.evaluator._call_builtin(self.name, list(args), kwargs)  # pyright: ignore[reportPrivateUsage]


def _bind_target(target: ast.expr, value: Any, scope: dict[str, Any]) -> None:
    if isinstance(target, ast.Name):
        scope[target.id] = value
        return
    assert isinstance(target, ast.Tuple)
    items = list(value)
    if len(items) != len(target.elts):
        raise EvalError(f'cannot unpack {len(items)} values into {len(target.elts)} names')
    for elt, item in zip(target.elts, items):
        _bind_target(elt, item, scope)


def evaluate(source: str, env: Mapping[str, Any], *, budget: NodeBudget) -> Any:
    """Parse and evaluate one expression. Convenience for tests and single-shot use."""
    return Evaluator(budget).eval(parse_expression(source), env)
