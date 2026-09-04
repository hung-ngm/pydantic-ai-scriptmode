"""Validate a plan whole, before anything runs, and report every issue at once."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic_ai_scriptmode._expr import BUILTIN_FUNCTIONS, RESERVED_NAMES, ExprError, free_names, parse_expression
from pydantic_ai_scriptmode._plan import CallStep, DeriveStep, Limits, Plan, Step
from pydantic_ai_scriptmode._teaching import Issue, issue


@dataclass(frozen=True)
class ToolSignature:
    """What the validator needs to know about a folded tool: its argument names."""

    name: str
    parameters: frozenset[str] | None = frozenset()
    """Accepted argument names; `None` when the tool accepts any (open `additionalProperties`)."""
    required: frozenset[str] = frozenset()


class ValidationError(Exception):
    """The plan is not executable. Carries every issue found."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__('\n'.join(i.render() for i in issues))


def _sources(step: Step) -> list[str]:
    if isinstance(step, CallStep):
        return [*step.args.values(), *(s for s in (step.each, step.fallback) if s is not None)]
    if isinstance(step, DeriveStep):
        return [step.expr]
    return [step.condition, step.value]


def _locally_bound(step: Step) -> set[str]:
    if isinstance(step, CallStep):
        return {n for n in (step.each_var, step.error_var) if n is not None}
    return set()


def _called_free_names(node: ast.expr) -> set[str]:
    called = {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    return called & free_names(node)


def input_fields(plan: Plan) -> set[str]:
    """The fields a plan reads off `input`, as `input.name`, `input['name']`, or `input.get('name')`.

    The dict methods a script may call on `input` are not fields.
    """
    fields: set[str] = set()
    sources = [source for step in plan.steps for source in _sources(step)]
    if plan.output is not None:
        sources.append(plan.output)
    for source in sources:
        tree = parse_expression(source)
        methods: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and _is_input(node.func.value):
                if node.func.attr in _INPUT_METHODS:
                    methods.add(id(node.func))
                if node.func.attr == 'get' and node.args:
                    key = _str_constant(node.args[0])
                    if key is not None:
                        fields.add(key)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _is_input(node.value) and id(node) not in methods:
                fields.add(node.attr)
            elif isinstance(node, ast.Subscript) and _is_input(node.value):
                key = _str_constant(node.slice)
                if key is not None:
                    fields.add(key)
    return fields


_INPUT_METHODS = frozenset({'get', 'keys', 'values', 'items'})


def _is_input(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == 'input'


def _str_constant(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def validate_plan(plan: Plan, *, tools: Mapping[str, ToolSignature], limits: Limits) -> list[Issue]:  # noqa: C901
    """Return every issue with `plan` against `tools` and `limits`; an empty list means executable."""
    issues: list[Issue] = []
    defined: set[str] = set()
    all_names = {s.name for s in plan.steps}
    worst_case_calls = 0

    if len(plan.steps) > limits.max_steps:
        issues.append(issue('too_many_steps', count=len(plan.steps), limit=limits.max_steps))

    for step in plan.steps:
        if step.name in RESERVED_NAMES:
            issues.append(issue('reserved_name', step.line, name=step.name))
        if step.name in defined:
            issues.append(issue('duplicate_step', step.line, name=step.name))
        bound = _locally_bound(step)
        for source in _sources(step):
            try:
                node = parse_expression(source)
            except ExprError as e:
                issues.append(issue(e.kind, step.line, **e.details))
                continue
            called = _called_free_names(node) - bound
            for name in sorted(free_names(node) - bound - called - {'input'}):
                if name in defined:
                    continue
                if name in all_names:
                    issues.append(issue('forward_reference', step.line, name=name, step=step.name))
                else:
                    issues.append(issue('undefined_name', step.line, name=name, step=step.name))
            for name in sorted(called):
                if name not in defined and name not in BUILTIN_FUNCTIONS:
                    issues.append(issue('unknown_function', step.line, name=name, step=step.name))
        if isinstance(step, CallStep):
            if step.each is not None and step.max_items is None:
                # The compiler never builds this; a hand-built plan can, and it would run unbounded.
                issues.append(issue('unbounded_for', step.line, iter=step.each))
            worst_case_calls += step.max_items if step.max_items is not None else 1
            if step.max_items is not None and step.max_items > limits.max_items_per_fanout:
                issues.append(
                    issue(
                        'fanout_too_large',
                        step.line,
                        count=step.max_items,
                        limit=limits.max_items_per_fanout,
                        step=step.name,
                    )
                )
            signature = tools.get(step.tool)
            if signature is None:
                issues.append(issue('unknown_tool', step.line, tool=step.tool, step=step.name))
            else:
                for arg in sorted(set(step.args) - signature.parameters) if signature.parameters is not None else ():
                    issues.append(issue('unknown_argument', step.line, argument=arg, tool=step.tool, step=step.name))
                for arg in sorted(signature.required - set(step.args)):
                    issues.append(issue('missing_argument', step.line, argument=arg, tool=step.tool, step=step.name))
        defined.add(step.name)

    if plan.output is not None:
        try:
            node = parse_expression(plan.output)
            for name in sorted(free_names(node) - defined - {'input'}):
                issues.append(issue('undefined_name', None, name=name, step='return'))
        except ExprError as e:
            issues.append(issue(e.kind, None, **e.details))

    if worst_case_calls > limits.max_total_calls:
        issues.append(issue('too_many_calls', count=worst_case_calls, limit=limits.max_total_calls))
    return issues
