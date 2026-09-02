# pydantic-ai-scriptmode

`ScriptMode` is a [Pydantic AI](https://ai.pydantic.dev) capability that gives an agent Code Mode's
one-round-trip batching without a sandbox. The model writes one short Python-subset script in a single
`run_script` tool call. The script is compiled into an inert plan of steps and pure expressions,
validated whole, and executed by a dataflow scheduler that can only invoke the agent's own tools.
Nothing the model writes runs as Python.

The design follows Vercel Labs' [callscript](https://github.com/vercel-labs/callscript), with a Python
authoring surface so it matches what `pydantic-ai-harness`'s `CodeMode` already teaches models. The
reasoning is in `docs/adr/`; the vocabulary used throughout is in `CONTEXT.md`.

## Usage

```python
from pydantic_ai import Agent
from pydantic_ai_scriptmode import ScriptMode

agent = Agent('anthropic:claude-sonnet-5', capabilities=[ScriptMode()])


@agent.tool_plain
async def list_issues(repo: str) -> list[dict[str, object]]: ...


@agent.tool_plain
async def close_issue(repo: str, number: int) -> str: ...
```

The model then sees one tool, `run_script`, whose description carries the signatures of the folded
tools, and writes scripts like:

```python
# Close stale issues and report how many
issues = await list_issues(repo='api')
stale = [i for i in issues if i['stale']]
if len(stale) == 0:
    return {'closed': 0}
closed = [await close_issue(repo='api', number=i['number']) for i in stale[:20]]
return {'closed': len(closed)}
```

## How it works

A `run_script` call passes through four stages. Each is a public function, so the engine can be used
without Pydantic AI (see "Using the engine directly").

1. **Compile** (`compile_script`). The script is parsed with the standard library `ast` and each
   statement is matched against the grammar table below. Every mismatch is collected and reported
   together as a `CompileError`. The result is a `Plan`: a tuple of frozen step dataclasses whose
   expressions are stored as source text, plus the intent and the output expression.
2. **Validate** (`validate_plan`). The plan is checked whole against the folded tools' signatures and
   the `Limits`: unknown tools or arguments, missing required arguments, undefined or forward
   references, reserved or duplicate step names, and the step, fan-out, and total-call bounds. All
   issues are returned at once; nothing has run yet.
3. **Execute** (`execute_plan`). A `Runner` derives the dataflow graph from the names each step reads
   and drives it: independent steps run concurrently, sequential `await`s run in written order, a
   guard is a fence that waits for everything before it. Calls go through one `Dispatch` function,
   which is the only way a plan reaches a tool. Expressions are evaluated by a tree-walking
   interpreter with a shared node budget; there is no `eval`.
4. **Record**. Every step settles to a `StepRecord` (done, skipped, error, or returned) keyed by name
   and by a hash of its authored form. The `Record` is stored per conversation, even when the run
   fails, so a corrected script reuses the steps that already settled.

## What a script may contain

| Statement | Compiles to |
| --- | --- |
| leading `# comment` or docstring | the plan's intent |
| `x = await tool(k=v)` | a call step |
| `await tool(k=v)` | an anonymous call step (`_callN`) |
| `x = <expression>` | a derivation step |
| `if cond: return value` | a guard step (a fence: everything before it settles first) |
| `x = [await tool(k=i.v) for i in xs[:N] if cond]` | a fan-out bounded by the slice, with an optional filter |
| `for i in xs[:N]: await tool(k=i.v)` | an anonymous fan-out |
| `a, b = await asyncio.gather(tool_a(...), tool_b(...))` | concurrent call steps |
| `try: x = await tool(...)` / `except Exception as e: x = fallback` | a call step with an error branch; `e` is the error message |
| `try: await tool(...)` / `except Exception: pass` | a call step that settles to `None` on failure |
| `await tool(..., _on_error='skip')` | the same, as a call option; in a fan-out only the failed items settle to `None` |
| `await tool(..., _reason='why')` | a call annotated for audit and approval |
| trailing `return value` | the run's output (else the last step's value) |

A fan-out bound must be a literal: `xs[:N]`, `xs[a:N]`, or a list display. Tool arguments are
keyword-only. Rejected outright: `while`, unbounded `for`, `def`, `class`, `import`, augmented
assignment, `return` before the last line, a tool call nested inside an expression, and a tool call
without `await`.

Expressions are a pure subset: literals, f-strings, names, containers, subscripts and slices, attribute
reads (dict keys work as attributes), comparisons, boolean and arithmetic operators (no `**`),
ternaries, lambdas, list and dict comprehensions, a whitelist of builtins (`len`, `sum`, `min`, `max`,
`sorted`, `reversed`, `enumerate`, `zip`, `any`, `all`, `abs`, `round`, `str`, `int`, `float`, `bool`,
`list`, `dict`, `set`, `range`), `json.dumps`/`json.loads`, non-mutating `str` methods, `list.index`
and `list.count`, and `dict.get`/`keys`/`values`/`items`. Every value stays JSON-shaped: `zip`,
`enumerate`, and `set` return lists. `input` is bound by the engine and is never reused from a record.

## Options

- `tools`: `'all'` (default), a list of tool names, or a `(ctx, tool_def) -> bool` predicate.
  Matching tools are folded into `run_script`; the rest stay native. Framework control tools,
  deferred tools, and other code-execution tools always stay native.
- `limits`: a `Limits` dataclass, below. The live numbers are rendered into the `run_script`
  description.
- `record_store`: a `RecordStore`, below. Defaults to in-memory.
- `max_retries`: retries for `run_script` itself (default 3). Compile errors, validation errors, and
  uncaught runtime errors all count.

### Limits

| Field | Default | Bounds |
| --- | --- | --- |
| `max_steps` | 20 | steps in one plan |
| `max_items_per_fanout` | 100 | the literal bound a fan-out may declare |
| `max_total_calls` | 200 | worst-case calls in one plan: every fan-out at its declared maximum |
| `max_concurrency` | 5 | calls in flight at once, across steps and fan-out items |
| `max_expression_nodes` | 100,000 | evaluation budget shared by every expression in one execution |
| `max_result_bytes` | 10 MiB | size of one call's JSON-encoded result before it is refused |

The first three are checked at validation, before anything runs. The last three are enforced during
execution. An oversized result fails the call, which the script's error branch may catch; a spent
expression budget fails the step outright.

### RecordStore

A store has two async methods keyed by `conversation_id`. Anything with this shape works:

```python
import json
from dataclasses import asdict

from pydantic_ai_scriptmode import Record, ScriptMode, StepRecord


class RedisRecordStore:
    def __init__(self, redis) -> None:
        self.redis = redis

    async def get(self, conversation_id: str) -> Record | None:
        raw = await self.redis.get(f'scriptmode:{conversation_id}')
        if raw is None:
            return None
        data = json.loads(raw)
        steps = {name: StepRecord(**entry) for name, entry in data.pop('steps').items()}
        return Record(steps=steps, **data)

    async def put(self, conversation_id: str, record: Record) -> None:
        await self.redis.set(f'scriptmode:{conversation_id}', json.dumps(asdict(record)))


agent = Agent(..., capabilities=[ScriptMode(record_store=RedisRecordStore(redis))])
```

The reuse rule is stricter than callscript's. A settled step is taken as given only when the record
holds an entry under the same name with the same authored hash **and** every step it reads was itself
reused. A step that reads `input` is never reused. `_reason` and line numbers are not part of the
hash, so rewording a reason does not invalidate a step.

## What the model sees on failure

Each stage that rejects a script raises `ModelRetry`, so the model gets one message and another turn.

- **Compile**: `The script could not be compiled:` followed by one `- line N: message` per issue. The
  message for each rejection kind is teaching copy from `_teaching.py`, written to name the construct
  the model reached for and the one it should use.
- **Validate**: `The script is not executable:` with the same list shape.
- **Execute**: `` Step `name` failed: <error> ``, followed by `Steps that settled and will be reused by
  a corrected script: a, b, c.` when any did. The corrected script should keep those steps unchanged.

A tool that raises, returns `ModelRetry`, fails argument validation, or is denied becomes a
`CallError` inside the engine, which the script's error branch can catch. `ApprovalRequired` and
`CallDeferred` propagate out of `run_script` exactly as they do in `CodeMode`; add a
`HandleDeferredToolCalls` capability to resolve them inline.

On success the tool returns `{'status': 'done' | 'returned', 'output': ...}`. The `ToolReturn`
metadata carries `plan` (the plan as plain data), `tool_calls`, and `tool_returns` (the nested parts
per call), so a run can be audited without re-executing it.

## Using the engine directly

The engine knows nothing about Pydantic AI. `dispatch` is any async callable taking a `CallStep` and
its evaluated arguments.

```python
from pydantic_ai_scriptmode import CallStep, Limits, ToolSignature, compile_script, execute_plan, validate_plan

plan = compile_script(script)
issues = validate_plan(
    plan, tools={'fetch': ToolSignature('fetch', frozenset({'url'}), frozenset({'url'}))}, limits=Limits()
)
assert not issues


async def dispatch(step: CallStep, args: dict[str, object]) -> object:
    return await my_tools[step.tool](**args)


result = await execute_plan(plan, dispatch=dispatch, input={'seed': 1})
result.status, result.output, result.record
```

## Development

```bash
make install
make all    # ruff format, ruff check, pyright strict, pytest
```
