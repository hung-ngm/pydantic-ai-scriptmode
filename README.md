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
4. **Record**. Every step settles to a `StepRecord` (done, skipped, error, returned, or suspended)
   keyed by name and by a hash of its authored form. The `Record` is stored per conversation (per
   conversation, tool, and input for a script tool), even when the run fails or parks, so a
   corrected or resumed script reuses the steps that already settled.

A call that needs an approval parks the run instead of failing it. If nothing resolved the
`ApprovalRequired` inline, the step settles as `suspended`, the steps that do not depend on it keep
running, and once nothing more can settle the record is saved and `run_script` itself raises
`ApprovalRequired`. Its metadata lists the intent and every parked call with its tool, arguments,
and `_reason`, so the approver sees what will run; one approval covers all of them. On the approved
re-run Pydantic AI re-issues the same `run_script` call, and the engine re-dispatches only the parked
steps, approved, with everything else reused from the record. A parked fan-out keeps its done items
and re-dispatches only the parked ones. A denial is answered by Pydantic AI before the toolset sees
it, so the parked steps stay parked and are asked again if a later script calls them; a step that
parks more than `max_suspend_attempts` times fails instead, with an error the script's error branch
can catch. A suspension never counts against `max_retries`. The run that parks and the run that
resumes must share a record store; the default lives in one process, and `SQLiteRecordStore` (below)
shares a file across processes.

The catalog of folded tools is rebuilt every step, so a tool discovered mid-run by `ToolSearch` is
callable from the next script either way. By default the catalog is rendered into the `run_script`
description, which providers key their prompt cache on, so each discovery rewrites the description
and busts the cache from that point. `ScriptMode(dynamic_catalog=True)` keeps the description static
and moves the catalog into the system instructions as a dynamic `InstructionPart`, which Anthropic
and Bedrock place after the cache breakpoint; a discovery is announced with one system message
naming the new tools. Turn it on when pairing `ScriptMode` with `ToolSearch`. With a fixed toolset
the default keeps the system prompt shorter, which is why it is off. This mirrors harness `CodeMode`.

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

A fan-out bound must be a literal: `xs[:N]`, `xs[a:N]`, or a list display, written on the fan-out or on
the derivation it iterates (`target = weak[:3]` then `for m in target`). N should be the most items
expected, not the limit: the validator adds every fan-out's N toward `max_total_calls`. Tool arguments are
keyword-only. Rejected outright: `while`, unbounded `for`, `def`, `class`, `import`, augmented
assignment, `return` before the last line, a tool call nested inside an expression, and a tool call
without `await`.

Expressions are a pure subset: literals, f-strings, names, containers, subscripts and slices, attribute
reads (dict keys work as attributes), comparisons, boolean and arithmetic operators (no `**`),
ternaries, lambdas, list and dict comprehensions, a whitelist of builtins (`len`, `sum`, `min`, `max`,
`sorted`, `reversed`, `enumerate`, `zip`, `any`, `all`, `abs`, `round`, `str`, `int`, `float`, `bool`,
`list`, `dict`, `set`, `range`), `json.dumps`/`json.loads`, non-mutating `str` methods, `list.index`
and `list.count`, and `dict.get`/`keys`/`values`/`items`. Every value stays JSON-shaped: `zip`,
`enumerate`, and `set` return lists. `input` is bound by the engine: `None` in `run_script`, the call's
arguments in a script tool.

## Options

- `tools`: `'all'` (default), a list of tool names, or a `(ctx, tool_def) -> bool` predicate.
  Matching tools are folded into `run_script`; the rest stay native. Framework control tools,
  deferred tools, and other code-execution tools always stay native.
- `limits`: a `Limits` dataclass, below. The live numbers are rendered into the `run_script`
  description.
- `record_store`: a `RecordStore`, below. Defaults to in-memory; `SQLiteRecordStore(path)` survives the
  process.
- `max_retries`: retries for `run_script` itself (default 3). Compile errors, validation errors, and
  uncaught runtime errors all count.
- `dynamic_catalog`: `False` by default. When `True`, the folded tools' signatures move out of the
  `run_script` description into the system instructions as a dynamic `InstructionPart`, and each
  tool discovered by `ToolSearch` is announced with a short system message. See "How it works".
- `scripts`: a list of `ScriptTool`s, below. Saved scripts served as tools.

### Script tools

A script that worked once can be kept: save its text under a name and the model calls it like any
tool, without authoring it again.

```python
from typing_extensions import TypedDict

from pydantic_ai_scriptmode import ScriptMode, ScriptTool


class CloseStaleParams(TypedDict):
    repo: str


close_stale = ScriptTool(
    'close_stale',
    """
# Close every stale issue in a repository
issues = await list_issues(repo=input.repo)
stale = [i for i in issues if i.stale]
closed = [await close_issue(repo=input.repo, number=i.number) for i in stale[:20]]
return {'closed': len(closed)}
""",
    parameters=CloseStaleParams,
    returns=dict[str, int],
)

agent = Agent(..., capabilities=[ScriptMode(scripts=[close_stale])])
```

The script is compiled where the tool is defined, so a script that does not compile raises
`CompileError` at import. The call's arguments are bound as `input`; `parameters` is a Python type
(a `TypedDict`, `BaseModel`, or dataclass, validated) or a JSON schema (checked for shape and
`required` keys only), and every `input.<field>` the script reads, including on the `return` line
and through `input.get('field')`, must be a declared parameter unless the schema is open. `returns`
is optional and only shapes the signature the model sees; `description` defaults to the intent line.

A script tool goes through `tools` like any other tool: by default it is folded and appears in the
catalog next to the tools it composes, so a script can call it; a predicate that excludes it keeps
it native. Folded is the better default: in the trial a native script tool was called from inside a
script anyway, costing a retry, and otherwise went unused. The saved script itself may call every tool eligible for folding, whether or not `tools`
folded it, plus the script tools declared before it in `scripts`, so script tools compose and a
cycle is impossible. A saved script that names a tool the agent does not have, or a name two tools
sanitize to, is a `UserError` when the tools are built; one that names a tool the agent has but
that is not available yet (undiscovered by `ToolSearch`, hidden by a `prepare` hook) is hidden for
that step, with one warning, and appears once the tool does. The call returns the plan's output,
whether the last line or a guard produced it. A failed step raises `ModelRetry` naming the step, so the model can change the arguments or give
up, and a script that called the tool catches it as a failed call. A call that needs approval parks
the script tool the same way it parks `run_script`, and the approval request's metadata names the
script tool; called from inside a script, the outer script parks and one approval resumes both.

Each script tool call keeps its own record, keyed by conversation, tool name, and input, so a saved
script never reuses a step the model's script settled, two calls with different inputs do not share
one, and the approved re-run finds the record it parked under. The record serves a retry or a
resume only: a call that completed is not replayed from it, so the same arguments later in the
conversation run the tools again.

### Limits

| Field | Default | Bounds |
| --- | --- | --- |
| `max_steps` | 20 | steps in one plan |
| `max_items_per_fanout` | 100 | the literal bound a fan-out may declare |
| `max_total_calls` | 500 | worst-case calls in one plan: every fan-out at its declared maximum |
| `max_concurrency` | 5 | calls in flight at once, across steps and fan-out items |
| `max_expression_nodes` | 100,000 | evaluation budget shared by every expression in one execution |
| `max_result_bytes` | 10 MiB | size of one call's JSON-encoded result before it is refused |
| `max_suspend_attempts` | 5 | times one step may park on an approval across runs before parking again fails it |

The first three are checked at validation, before anything runs. The last four are enforced during
execution. An oversized result or an exhausted suspend budget fails the call, which the script's
error branch may catch; a spent expression budget fails the step outright.

### RecordStore

The default `InMemoryRecordStore` is a dict, so a run that parks in one process cannot resume in
another. `SQLiteRecordStore(path)` keeps records in one SQLite file through the standard library,
so the run that parks and the run that resumes need only share the path:

```python
from pydantic_ai_scriptmode import ScriptMode, SQLiteRecordStore

store = SQLiteRecordStore('records.sqlite')
agent = Agent(..., capabilities=[ScriptMode(record_store=store)])
```

`':memory:'` gives a store that lives with the instance, for tests. `put` is last-write-wins and
there is no `delete`; the table is `records(key, record, updated_at)` with `updated_at` in ISO 8601
UTC, so a host prunes with `DELETE FROM records WHERE updated_at < ?`. A writer in another process
is waited for `timeout` seconds (default 5), then `sqlite3.OperationalError` escapes. `close()`
releases the connection.

A store has two async methods keyed by a string: the conversation id for `run_script`, and the
conversation id, tool name, and input hash for a script tool. `Record.to_dict()` is a JSON-safe
object and `Record.from_dict()` rebuilds it, so a store only moves that object. Anything with this
shape works:

```python
import json

from pydantic_ai_scriptmode import Record, ScriptMode


class RedisRecordStore:
    def __init__(self, redis) -> None:
        self.redis = redis

    async def get(self, key: str) -> Record | None:
        raw = await self.redis.get(f'scriptmode:{key}')
        return None if raw is None else Record.from_dict(json.loads(raw))

    async def put(self, key: str, record: Record) -> None:
        await self.redis.set(f'scriptmode:{key}', json.dumps(record.to_dict()))


agent = Agent(..., capabilities=[ScriptMode(record_store=RedisRecordStore(redis))])
```

The reuse rule is stricter than callscript's. A settled step is taken as given only when the record
holds an entry under the same name with the same authored hash **and** every step it reads was itself
reused. A step that reads `input` is reused only when the record was produced under the same `input`
(the record keeps it), which for `run_script` is always `None` and for a script tool is the call's
arguments. `_reason` and line numbers are not part of the hash, so rewording a reason does not
invalidate a step.

## What the model sees on failure

Each stage that rejects a script raises `ModelRetry`, so the model gets one message and another turn.

- **Compile**: `The script could not be compiled:` followed by one `- line N: message` per issue. The
  message for each rejection kind is teaching copy from `_teaching.py`, written to name the construct
  the model reached for and the one it should use.
- **Validate**: `The script is not executable:` with the same list shape.
- **Execute**: `` Step `name` failed: <error> ``, followed by `Steps that settled and will be reused by
  a corrected script: a, b, c.` when any did. The corrected script should keep those steps unchanged.

A tool that raises, returns `ModelRetry`, fails argument validation, or is denied becomes a
`CallError` inside the engine, which the script's error branch can catch. `ApprovalRequired` is
resolved inline when a `HandleDeferredToolCalls` capability handles it, and otherwise parks the run
as described under "How it works"; the agent then needs `DeferredToolRequests` among its output
types, and Pydantic AI's own error says so when it is missing. `CallDeferred` must be resolved
inline, as in `CodeMode`: a nested call is not one the model made, so its external result has no
way back in. Without a handler the run fails with a `UserError` that says so.

On success the tool returns `{'status': 'done' | 'returned', 'output': ...}`. The `ToolReturn`
metadata carries `plan` (the plan as plain data), `tool_calls`, and `tool_returns` (the nested parts
per call), so a run can be audited without re-executing it. After a suspension only the resumed
run returns, so its metadata holds the parts of the re-dispatched calls; the calls made before the
park are in the approval request's metadata (the parked ones) and in the record (every step's value).

## Using the engine directly

The engine knows nothing about Pydantic AI. `dispatch` is any async callable taking a `CallStep`,
its evaluated arguments, and a keyword `resolution`, which is `None` unless the call was parked by a
`Suspend` on an earlier execution and `execute_plan(resolutions={step: answer})` is re-entering it.

```python
from pydantic_ai_scriptmode import CallStep, Limits, ToolSignature, compile_script, execute_plan, validate_plan

plan = compile_script(script)
issues = validate_plan(
    plan, tools={'fetch': ToolSignature('fetch', frozenset({'url'}), frozenset({'url'}))}, limits=Limits()
)
assert not issues


async def dispatch(step: CallStep, args: dict[str, object], *, resolution: object = None) -> object:
    return await my_tools[step.tool](**args)


result = await execute_plan(plan, dispatch=dispatch, input={'seed': 1})
result.status, result.output, result.record
```

## Development

```bash
make install
make all    # ruff format, ruff check, pyright strict, pytest
```
