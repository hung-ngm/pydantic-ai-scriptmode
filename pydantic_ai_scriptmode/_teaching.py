"""Teaching copy: the message the model reads when a script is rejected.

Every rejection the compiler or validator raises has a kind (a key of `TEACHING`) and a few
details. The message for each kind is one format string, written by hand, that tells the model
the right spelling instead of only what was wrong. `explain` renders it.

Keep messages short, concrete, and in the vocabulary of `CONTEXT.md`: script, step, call,
derivation, guard, fan-out. Name the construct the model reached for and the one it should use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RejectionKind = Literal[
    # --- statements the language does not have (compile time) ---
    'while_loop',  # details: none
    'unbounded_for',  # details: iter (source text of the iterable)
    'for_body',  # details: none. A `for` whose body is not exactly one call statement
    'function_def',  # details: name
    'class_def',  # details: name
    'import_statement',  # details: none
    'augmented_assignment',  # details: target
    'unsupported_statement',  # details: node (the ast class name)
    'bare_expression',  # details: none. An expression statement that is not a call
    'unassigned_call',  # details: tool. Reserved for later; currently anonymous calls are allowed
    'multiple_targets',  # details: none. `a = b = ...` or starred / attribute targets
    'return_not_last',  # details: none. A plain `return` before the end of the script
    'guard_shape',  # details: none. `if` whose body is not a single `return`, or that has `else`
    'try_shape',  # details: none. `try` whose body or handler is not the supported single statement
    'gather_shape',  # details: none. `asyncio.gather` target count does not match its calls
    'call_positional_args',  # details: tool
    'call_not_awaited',  # details: tool
    'call_nested',  # details: tool. A tool call inside an expression rather than a step of its own
    'unknown_call_option',  # details: option. A `_something=` kwarg that is not `_reason` / `_on_error`
    'bad_on_error',  # details: value
    'syntax_error',  # details: message
    # --- expressions ---
    'unsupported_expression',  # details: node (the ast class name)
    'unknown_function',  # details: name (the parser raises it without a step)
    'dunder_attribute',  # details: name
    'unsupported_method',  # details: name
    # --- plan checks (validation) ---
    'duplicate_step',  # details: name
    'reserved_name',  # details: name. Step named after a builtin, `input`, `asyncio`, or `json`
    'undefined_name',  # details: name, step
    'forward_reference',  # details: name, step
    'unknown_tool',  # details: tool, step
    'unknown_argument',  # details: argument, tool, step
    'missing_argument',  # details: argument, tool, step
    'too_many_steps',  # details: count, limit
    'fanout_too_large',  # details: count, limit, step
    'too_many_calls',  # details: count, limit
]

# Each value is a `str.format` template; the details listed next to each kind above are the only
# names it may use in braces. Every line is read under `The script could not be compiled:`, so it
# names the construct reached for and the one to use instead. An empty string falls back to a bare
# `kind: details` rendering so the engine keeps working while copy is missing.
TEACHING: dict[RejectionKind, str] = {
    # --- statements the language does not have ---
    'while_loop': (
        'a script has no `while` loop. Fan out over a bounded list instead: '
        '`xs = [await tool(k=i) for i in items[:N]]`, or split the work across scripts.'
    ),
    'unbounded_for': (
        'a fan-out over `{iter}` has no declared bound. Slice it with a literal, `{iter}[:N]`, '
        'or write out a list; the bound is how the plan knows its worst-case call count.'
    ),
    'for_body': (
        'a `for` is a fan-out and its body must be exactly one awaited call over one loop name: '
        '`for i in xs[:N]: await tool(k=i)`. Put any other work in a derivation before or after it.'
    ),
    'function_def': (
        'a script cannot define `{name}`; there are no functions. Write the steps in order at the '
        'top level and reuse values by their step name.'
    ),
    'class_def': ('a script cannot define class `{name}`. Build plain dicts and lists in a derivation instead.'),
    'import_statement': (
        'a script has no imports. `asyncio.gather` and `json.dumps`/`json.loads` are already '
        'available; everything else is a folded tool from the catalog.'
    ),
    'augmented_assignment': (
        'steps are settled once, so `{target} += ...` cannot update `{target}`. '
        'Give the new value a new step name: `{target}2 = {target} + ...`.'
    ),
    'unsupported_statement': (
        'a `{node}` statement is not part of a script. A script is only calls (`x = await tool(k=v)`), '
        'derivations (`x = <expression>`), guards (`if cond: return value`), bounded fan-outs, '
        '`try`/`except` error branches, and a trailing `return`.'
    ),
    'bare_expression': (
        'an expression on its own line does nothing. Name it as a derivation, `x = <expression>`, '
        'or `await` it if it is a tool call.'
    ),
    'unassigned_call': (
        'the call to `{tool}` needs a step name so later steps can reference it: `x = await {tool}(...)`.'
    ),
    'multiple_targets': (
        'each step settles exactly one name. Use `x = ...` with a plain name; chained targets, '
        'attribute or index targets, and starred targets are not steps. Tuple targets are only for '
        '`a, b = await asyncio.gather(...)`.'
    ),
    'return_not_last': (
        'a `return` before the last line ends the script for every path. To end early on a '
        'condition, write a guard, `if cond: return value`; keep the unconditional `return` last.'
    ),
    'guard_shape': (
        'an `if` is a guard and must be exactly `if cond: return value` with no `else` and no other '
        'body. Compute branch values with a ternary derivation instead: `x = a if cond else b`.'
    ),
    'try_shape': (
        'a `try` is an error branch for one call: `try: x = await tool(...)` then '
        '`except Exception as e: x = <fallback>` assigning the same name, or `except Exception: pass`. '
        'No `else`, `finally`, or extra statements.'
    ),
    'gather_shape': (
        '`asyncio.gather` must be awaited into one name per call: '
        '`a, b = await asyncio.gather(tool_a(...), tool_b(...))`, with as many names as calls.'
    ),
    'call_positional_args': (
        'tool arguments are keyword-only. Write `{tool}(name=value, ...)` using the parameter names from the catalog.'
    ),
    'call_not_awaited': ('the call to `{tool}` is missing `await`. Every call is a step: `x = await {tool}(...)`.'),
    'call_nested': (
        '`{tool}` is a call inside an expression, and calls must be steps of their own. '
        'Await it first, `x = await ...`, then use `x` in the expression.'
    ),
    'unknown_call_option': (
        "`{option}` is not a call option. The only underscore options are `_reason='why'` "
        "and `_on_error='skip'`; tool parameters never start with an underscore."
    ),
    'bad_on_error': (
        "`_on_error={value}` is not a choice. Use `_on_error='skip'` to settle the step to `None` on "
        'failure, or leave it out to fail the run. For a custom fallback use a `try`/`except` error branch.'
    ),
    'syntax_error': ('the script is not valid Python: {message}. Fix the syntax and resend the whole script.'),
    # --- expressions ---
    'unsupported_expression': (
        'a `{node}` expression is not part of the pure subset. Expressions may use literals, '
        'f-strings, names, containers, subscripts, attributes, comparisons, boolean and arithmetic '
        'operators (no `**`), ternaries, comprehensions, and the listed builtins.'
    ),
    'unknown_function': (
        '`{name}` is not a builtin or a folded tool. Builtins are len, sum, min, max, '
        'sorted, reversed, enumerate, zip, any, all, abs, round, str, int, float, bool, list, dict, '
        'set, range, plus json.dumps and json.loads. Tools must be awaited as their own step.'
    ),
    'dunder_attribute': (
        '`{name}` is a dunder attribute and expressions cannot read one. Use the plain fields and keys of the value.'
    ),
    'unsupported_method': (
        '`.{name}()` is not an allowed method. Expressions may call non-mutating `str` methods, '
        '`list.index` and `list.count`, and `dict.get`/`keys`/`values`/`items`; build new values '
        'with a comprehension instead of mutating.'
    ),
    # --- plan checks ---
    'duplicate_step': ('step `{name}` is defined twice; a step settles once. Give the second one a new name.'),
    'reserved_name': (
        '`{name}` is reserved (a builtin, `input`, `asyncio`, or `json`) and cannot name a step. Pick another name.'
    ),
    'undefined_name': ('`{name}` in step `{step}` is not defined. Reference an earlier step by its name, or `input`.'),
    'forward_reference': (
        'step `{step}` references `{name}`, which is defined later. Steps read only what settled '
        'before them; move `{name}` above `{step}`.'
    ),
    'unknown_tool': (
        '`{tool}` in step `{step}` is not a folded tool. Use one of the tools in the catalog, spelled exactly.'
    ),
    'unknown_argument': (
        '`{tool}` has no parameter `{argument}` (step `{step}`). Check the parameter names in the catalog.'
    ),
    'missing_argument': (
        '`{tool}` requires `{argument}` (step `{step}`). Pass it as a keyword: `{tool}({argument}=...)`.'
    ),
    'too_many_steps': (
        'the script has {count} steps and the limit is {limit}. Fold repeated calls into a fan-out, '
        'or split the work across scripts.'
    ),
    'fanout_too_large': (
        'the fan-out in step `{step}` declares {count} items and the limit is {limit}. '
        'Slice to `[:{limit}]` or fewer, or fan out in more than one script.'
    ),
    'too_many_calls': (
        'the script could make {count} calls at worst and the limit is {limit}. Tighten fan-out '
        'bounds or drop calls; the count adds every fan-out at its declared maximum.'
    ),
}


@dataclass(frozen=True)
class Issue:
    """One thing wrong with a script, located by line."""

    kind: RejectionKind
    message: str
    line: int | None = None

    def render(self) -> str:
        """Render as `line N: message`, or just the message when the line is unknown."""
        return f'line {self.line}: {self.message}' if self.line is not None else self.message


def explain(kind: RejectionKind, **details: object) -> str:
    """Render the teaching message for `kind`.

    Falls back to `kind (k=v, ...)` when no copy has been written for the kind yet, so a missing
    template is visible in the rejection rather than a `KeyError` at the worst moment.
    """
    template = TEACHING.get(kind, '')
    if template:
        return template.format(**details)
    suffix = ', '.join(f'{k}={v!r}' for k, v in details.items())
    return f'{kind} ({suffix})' if suffix else kind


def issue(kind: RejectionKind, line: int | None = None, **details: object) -> Issue:
    """Build an `Issue` with its message rendered from the teaching table."""
    return Issue(kind=kind, message=explain(kind, **details), line=line)
