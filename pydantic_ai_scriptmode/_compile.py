"""Compile a script into a plan.

The grammar is a table from statement shape to step. Anything not in the table is a rejection
with a kind from `_teaching`, and all rejections in a script are reported together.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from pydantic_ai_scriptmode._expr import BUILTIN_FUNCTIONS, MODULE_FUNCTIONS, ExprError, check_expression
from pydantic_ai_scriptmode._plan import CallStep, DeriveStep, GuardStep, OnError, Plan, Step
from pydantic_ai_scriptmode._teaching import Issue, RejectionKind, issue

_CALL_OPTIONS = frozenset({'_reason', '_on_error'})


class CompileError(Exception):
    """The script could not be compiled. Carries every issue found."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__('\n'.join(i.render() for i in issues))


@dataclass
class _ParsedCall:
    tool: str
    args: dict[str, str]
    reason: str | None
    on_error: OnError


@dataclass
class _Compiler:
    issues: list[Issue] = field(default_factory=list[Issue])
    steps: list[Step] = field(default_factory=list[Step])
    # Names of the call step(s) the next call must wait for: sequential awaits are ordered so a
    # script's side effects happen in the order it was written. A gather is one group.
    last_calls: tuple[str, ...] = ()
    output: str | None = None
    defined: set[str] = field(default_factory=set[str])
    # Literal bounds carried by derivations (`target = weak[:3]`), so a fan-out over the bare
    # name inherits the bound. A rebinding drops the entry.
    bounds: dict[str, int] = field(default_factory=dict[str, int])

    def define(self, name: str, bound: int | None = None) -> None:
        self.defined.add(name)
        if bound is None:
            self.bounds.pop(name, None)
        else:
            self.bounds[name] = bound

    def reject(self, at: ast.AST, kind: RejectionKind, **details: object) -> None:
        self.issues.append(issue(kind, getattr(at, 'lineno', None), **details))

    def anonymous(self, prefix: str) -> str:
        return f'_{prefix}{len(self.steps) + 1}'

    # -- statements ------------------------------------------------------------------------

    def statement(self, node: ast.stmt, *, is_last: bool) -> None:
        if isinstance(node, ast.Assign):
            self.assign(node, node.targets, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            self.assign(node, [node.target], node.value)
        elif isinstance(node, ast.Expr):
            self.expression_statement(node)
        elif isinstance(node, ast.If):
            self.guard(node)
        elif isinstance(node, ast.For):
            self.for_loop(node)
        elif isinstance(node, ast.Try):
            self.try_statement(node)
        elif isinstance(node, ast.Return):
            if not is_last:
                self.reject(node, 'return_not_last')
            else:
                self.output = self.expression(node.value) if node.value is not None else 'None'
        elif isinstance(node, ast.While):
            self.reject(node, 'while_loop')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.reject(node, 'function_def', name=node.name)
        elif isinstance(node, ast.ClassDef):
            self.reject(node, 'class_def', name=node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self.reject(node, 'import_statement')
        elif isinstance(node, ast.AugAssign):
            self.reject(node, 'augmented_assignment', target=ast.unparse(node.target))
        elif isinstance(node, ast.Pass):
            pass
        else:
            self.reject(node, 'unsupported_statement', node=type(node).__name__)

    def assign(self, node: ast.stmt, targets: list[ast.expr], value: ast.expr) -> None:
        if len(targets) != 1:
            self.reject(node, 'multiple_targets')
            return
        target = targets[0]
        if isinstance(target, ast.Tuple):
            self.gather(node, target, value)
            return
        if not isinstance(target, ast.Name):
            self.reject(node, 'multiple_targets')
            return
        name = target.id
        if isinstance(value, ast.Await):
            self.call_step(node, name, value.value)
        elif isinstance(value, ast.ListComp) and isinstance(value.elt, ast.Await):
            self.fan_out(node, name, value.elt.value, value.generators)
        elif isinstance(value, ast.Call) and self.is_tool_call(value):
            self.reject(node, 'call_not_awaited', tool=ast.unparse(value.func))
        else:
            source = self.expression(value)
            if source is not None:
                self.steps.append(DeriveStep(name=name, expr=source, line=node.lineno))
                self.define(name, _slice_bound(value))

    def expression_statement(self, node: ast.Expr) -> None:
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return  # a docstring anywhere but first is a comment
        if isinstance(value, ast.Await):
            self.call_step(node, self.anonymous('call'), value.value)
        elif isinstance(value, ast.Call) and self.is_tool_call(value):
            self.reject(node, 'call_not_awaited', tool=ast.unparse(value.func))
        else:
            self.reject(node, 'bare_expression')

    def guard(self, node: ast.If) -> None:
        if node.orelse or len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
            self.reject(node, 'guard_shape')
            return
        ret = node.body[0]
        condition = self.expression(node.test)
        value = self.expression(ret.value) if ret.value is not None else 'None'
        if condition is not None and value is not None:
            self.steps.append(
                GuardStep(name=self.anonymous('guard'), condition=condition, value=value, line=node.lineno)
            )

    def for_loop(self, node: ast.For) -> None:
        body_ok = (
            len(node.body) == 1 and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Await)
        )
        if node.orelse or not body_ok:
            self.reject(node, 'for_body')
            return
        awaited = node.body[0]
        assert isinstance(awaited, ast.Expr) and isinstance(awaited.value, ast.Await)
        generator = ast.comprehension(target=node.target, iter=node.iter, ifs=[], is_async=0)
        self.fan_out(node, self.anonymous('call'), awaited.value.value, [generator])

    def try_statement(self, node: ast.Try) -> None:
        shape_ok = (
            len(node.body) == 1
            and len(node.handlers) == 1
            and not node.orelse
            and not node.finalbody
            and len(node.handlers[0].body) == 1
        )
        if not shape_ok:
            self.reject(node, 'try_shape')
            return
        body, handler = node.body[0], node.handlers[0]
        name, call = _assigned_call(body)
        if call is None:
            self.reject(node, 'try_shape')
            return
        recovery = handler.body[0]
        if isinstance(recovery, ast.Pass):
            fallback = 'None'
        elif isinstance(recovery, ast.Assign) and len(recovery.targets) == 1 and _name_of(recovery.targets[0]) == name:
            fallback = self.expression(recovery.value)
            if fallback is None:
                return
        else:
            self.reject(node, 'try_shape')
            return
        parsed = self.parse_call(node, call)
        if parsed is None:
            return
        self.append_call(
            CallStep(
                name=name or self.anonymous('call'),
                tool=parsed.tool,
                args=parsed.args,
                reason=parsed.reason,
                on_error=parsed.on_error,
                fallback=fallback,
                error_var=handler.name,
                after=self.last_calls,
                line=node.lineno,
            )
        )

    # -- calls -------------------------------------------------------------------------------

    def call_step(self, node: ast.stmt, name: str, call: ast.expr) -> None:
        if isinstance(call, ast.Call) and _is_gather(call):
            self.reject(node, 'gather_shape')
            return
        parsed = self.parse_call(node, call)
        if parsed is None:
            return
        self.append_call(
            CallStep(
                name=name,
                tool=parsed.tool,
                args=parsed.args,
                reason=parsed.reason,
                on_error=parsed.on_error,
                after=self.last_calls,
                line=node.lineno,
            )
        )

    def fan_out(self, node: ast.stmt, name: str, call: ast.expr, generators: list[ast.comprehension]) -> None:
        if len(generators) != 1:
            self.reject(node, 'for_body')
            return
        gen = generators[0]
        target = gen.target
        if not isinstance(target, ast.Name):
            self.reject(node, 'for_body')
            return
        bound = _slice_bound(gen.iter)
        if bound is None and isinstance(gen.iter, ast.Name):
            bound = self.bounds.get(gen.iter.id)
        if bound is None:
            self.reject(node, 'unbounded_for', iter=ast.unparse(gen.iter))
            return
        parsed = self.parse_call(node, call)
        if parsed is None:
            return
        var = target.id
        each_node: ast.expr = gen.iter
        if gen.ifs:
            each_node = ast.ListComp(
                elt=ast.Name(id=var, ctx=ast.Load()),
                generators=[ast.comprehension(target=target, iter=gen.iter, ifs=gen.ifs, is_async=0)],
            )
        each = self.expression(each_node)
        if each is None:
            return
        self.append_call(
            CallStep(
                name=name,
                tool=parsed.tool,
                args=parsed.args,
                reason=parsed.reason,
                on_error=parsed.on_error,
                each=each,
                each_var=var,
                max_items=bound,
                after=self.last_calls,
                line=node.lineno,
            )
        )

    def gather(self, node: ast.stmt, target: ast.Tuple, value: ast.expr) -> None:
        if not (isinstance(value, ast.Await) and isinstance(value.value, ast.Call) and _is_gather(value.value)):
            self.reject(node, 'multiple_targets')
            return
        calls = value.value.args
        names = [_name_of(t) for t in target.elts]
        if len(calls) != len(names) or any(n is None for n in names) or value.value.keywords:
            self.reject(node, 'gather_shape')
            return
        group: list[CallStep] = []
        for name, call in zip(names, calls):
            assert name is not None
            parsed = self.parse_call(node, call)
            if parsed is None:
                continue
            group.append(
                CallStep(
                    name=name,
                    tool=parsed.tool,
                    args=parsed.args,
                    reason=parsed.reason,
                    on_error=parsed.on_error,
                    after=self.last_calls,
                    line=node.lineno,
                )
            )
        self.steps.extend(group)
        for s in group:
            self.define(s.name)
        self.last_calls = tuple(s.name for s in group)

    def append_call(self, step: CallStep) -> None:
        self.steps.append(step)
        self.define(step.name)
        self.last_calls = (step.name,)

    def is_tool_call(self, call: ast.Call) -> bool:
        """Whether a bare call reads as a forgotten `await`: a plain name that is neither a builtin nor a step."""
        func = call.func
        if not isinstance(func, ast.Name):
            return False
        return func.id not in BUILTIN_FUNCTIONS and func.id not in MODULE_FUNCTIONS and func.id not in self.defined

    def parse_call(self, node: ast.stmt, call: ast.expr) -> _ParsedCall | None:
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            self.reject(node, 'call_nested', tool=ast.unparse(call))
            return None
        tool = call.func.id
        if call.args:
            self.reject(node, 'call_positional_args', tool=tool)
            return None
        args: dict[str, str] = {}
        reason: str | None = None
        on_error: OnError = 'fail'
        ok = True
        for kw in call.keywords:
            if kw.arg is None:
                self.reject(node, 'unknown_call_option', option='**')
                ok = False
            elif kw.arg == '_reason':
                reason = ast.unparse(kw.value) if not isinstance(kw.value, ast.Constant) else str(kw.value.value)
            elif kw.arg == '_on_error':
                if isinstance(kw.value, ast.Constant) and kw.value.value in ('fail', 'skip'):
                    on_error = kw.value.value
                else:
                    self.reject(node, 'bad_on_error', value=ast.unparse(kw.value))
                    ok = False
            elif kw.arg.startswith('_'):
                self.reject(node, 'unknown_call_option', option=kw.arg)
                ok = False
            else:
                source = self.expression(kw.value)
                if source is None:
                    ok = False
                else:
                    args[kw.arg] = source
        return _ParsedCall(tool=tool, args=args, reason=reason, on_error=on_error) if ok else None

    def expression(self, node: ast.expr) -> str | None:
        """Check an expression and return its source, or record the rejection and return `None`."""
        try:
            check_expression(node)
        except ExprError as e:
            self.issues.append(issue(e.kind, getattr(node, 'lineno', None), **e.details))
            return None
        return ast.unparse(node)


def _is_gather(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == 'asyncio'
        and func.attr == 'gather'
    )


def _name_of(node: ast.expr) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _assigned_call(stmt: ast.stmt) -> tuple[str | None, ast.expr | None]:
    """`x = await call(...)` gives `('x', call)`; `await call(...)` gives `(None, call)`; else `(None, None)`."""
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.value, ast.Await):
        return _name_of(stmt.targets[0]), stmt.value.value
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await):
        return None, stmt.value.value
    return None, None


def _slice_bound(node: ast.expr) -> int | None:
    """The literal upper bound a fan-out iterable declares, or `None` when it declares none.

    `xs[:N]` and `xs[a:N]` are bounded by `N` (minus `a`); a list display is bounded by its length.
    A bare name is bounded when its derivation was one of these; see `_Compiler.bounds`.
    """
    if isinstance(node, ast.List):
        return len(node.elts)
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
        s = node.slice
        if s.step is not None or not (isinstance(s.upper, ast.Constant) and isinstance(s.upper.value, int)):
            return None
        lower = 0
        if s.lower is not None:
            if not (isinstance(s.lower, ast.Constant) and isinstance(s.lower.value, int)):
                return None
            lower = s.lower.value
        return max(s.upper.value - lower, 0)
    return None


def _intent(source: str, module: ast.Module) -> str | None:
    first = source.lstrip().splitlines()[0] if source.strip() else ''
    if first.startswith('#'):
        return first.lstrip('# ').strip() or None
    doc = ast.get_docstring(module)
    return doc.strip().splitlines()[0] if doc else None


def compile_script(source: str) -> Plan:
    """Compile `source` to a `Plan`, or raise `CompileError` with every issue found."""
    try:
        module = ast.parse(source)
    except SyntaxError as e:
        raise CompileError([issue('syntax_error', e.lineno, message=e.msg)]) from e
    compiler = _Compiler()
    body = module.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    for i, stmt in enumerate(body):
        compiler.statement(stmt, is_last=i == len(body) - 1)
    if compiler.issues:
        raise CompileError(compiler.issues)
    return Plan(steps=tuple(compiler.steps), intent=_intent(source, module), output=compiler.output)
