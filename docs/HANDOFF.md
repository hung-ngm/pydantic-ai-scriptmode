# Handoff: pydantic-ai-scriptmode

Date: 2026-09-04
Workspace: `/Users/hungng/Documents/AI/experiments/pydantic-experiments/`
Project: `pydantic-ai-scriptmode/`
This file is the single source of truth for progress. Update it in place at the end of each
session; do not write handoff copies elsewhere (no temp-directory copies, no progress in memory).

## Where things stand

Backlog items 0 to 4 are done: each has an accepted ADR, was built by TDD one commit per behaviour,
reviewed with `code-review` at `medium`, and pushed. Item 5, a JS surface, is closed without code by
ADR 0007 (accepted 2026-09-04): the reasons and the build plan are in the ADR, and the reopening
condition is a model that cannot write the Python subset after the teaching copy. Item 6,
upstreaming to `pydantic-ai-harness`, has its ADR (0008, accepted 2026-09-04) and the part of it
that can be done before asking: the Temporal and DBOS composition tests the harness requires pass,
and the capability-request issue is drafted in `docs/upstream/issue.md`. The engine changed once for
it: `Runner.schedule` wakes on an `asyncio.Event` instead of `asyncio.wait`, which Temporal's
workflow sandbox warns is non-deterministic (this suite errors on warnings). What is left is the user's: post the issue, publish 0.1.0 to PyPI, and
wait for a maintainer's answer before any port (see "Next session"). `make all` (ruff format, ruff
check, pyright strict, pytest) is green: 236 passed with the `durability` group installed; without
it, 231 passed and the two durability modules skipped at module level (the only skips), no xfails.

| Item | ADR | Commits on `main` | Done |
| --- | --- | --- | --- |
| Package, engine, adapters, README, first trial | 0001, 0002 | `79005aa` to `1c87782` | 2026-09-03 |
| 0. Fan-out bound through a derivation | (none) | `57517ff` | 2026-09-03 |
| 1. `dynamic_catalog` | 0003 | `f52fe14` to `e2d9840` | 2026-09-03 |
| 2. Suspend and detach | 0004 | `3a0fc05` to `3ee811f` | 2026-09-03 |
| 3. Script tools | 0005 | `ef394a3` to `23d2b06` | 2026-09-04 |
| 4. Durable `RecordStore` | 0006 | `879088f` to `5c51cf7` | 2026-09-04 |
| Tutor harness: Logfire instrumentation (the user's) | (none) | `caa6567`, `005dd57` | 2026-09-04 |
| 5. JS surface: closed, no code | 0007 | `6320b90` | 2026-09-04 |
| 6. Upstreaming: ADR, durability tests, issue draft | 0008 | `1274745` to `a7cee38` | 2026-09-04, waiting on the user and the maintainers |

`git log` has every commit with a one-line message that says what behaviour it added; this file
does not repeat them.

Remote: `origin` is the private repo `https://github.com/hung-ngm/pydantic-ai-scriptmode`;
`main` tracks `origin/main` and is in sync. Commit straight to `main` and push after each commit;
no force-push, no other branches.

Nothing is uncommitted. The user's Logfire instrumentation of `examples/tutor.py` (four metrics per
run, `logfire>=4.41.0` in the `examples` group) was carried onto HEAD and committed on 2026-09-04.
One review finding about it is still open and is the user's call: `logfire.configure()` runs at
import with `send_to_logfire` defaulting to `True`, so a clone without `logfire auth` or a token
raises or prompts before `main()`; `send_to_logfire='if-token-present'` (and `console=False` to keep
the printed trace clean) would fix it.

Read these first, in order. Do not restate them here.

- `README.md`: usage, "How it works", grammar table, options, retry messages, `RecordStore`.
- `CONTEXT.md`: glossary (19 terms). Use these words in code, docs, tests, and this file.
- `docs/adr/0001-*.md` to `0008-*.md`: why inert plan, why Python surface, why the catalog can
  move into instructions, why a parked call resumes from the record, why a saved script is a tool
  served by the toolset, why the package serializes the record and ships a SQLite store, why there
  is no JS surface, why upstreaming goes issue first and vendored. Each ends with the options it
  rejected; do not re-litigate them without new facts.
- `docs/upstream/issue.md`: the capability-request draft for the harness, in its template's fields.
- Project memory `~/.claude/projects/-Users-hungng-Documents-AI-experiments-pydantic-experiments/memory/scriptmode-project.md`
  (loaded automatically via `MEMORY.md`).

## Package layout

`pydantic_ai_scriptmode/`, engine first, adapters last. Every module has a module docstring saying
what it owns.

| Module | Owns | Tests |
| --- | --- | --- |
| `_teaching.py` | `RejectionKind`, `TEACHING` table, `Issue`, `explain`, `issue` | `tests/test_teaching.py` |
| `_expr.py` | expression subset: `parse_expression`, `free_names`, `Evaluator`, `NodeBudget` | `tests/test_expr.py` |
| `_plan.py` | `CallStep`, `DeriveStep`, `GuardStep`, `Plan`, `Limits`, `step_hash` | via compile tests |
| `_compile.py` | `compile_script` -> `Plan` or `CompileError` (all issues at once) | `tests/test_compile.py` |
| `_validate.py` | `validate_plan`, `ToolSignature` | `tests/test_validate.py` |
| `_record.py` | `Record` (with `input`, `to_dict`, `from_dict`), `StepRecord`, `ItemRecord`, `RecordStore` protocol (keyed by a string), `InMemoryRecordStore`, `reusable_steps`, `parked_steps` | `tests/test_record.py`, `tests/test_execute.py::TestRecordReuse`, `::TestSuspend` |
| `_stores.py` | `SQLiteRecordStore(path, timeout=)`: one table, one owned thread and connection, `close()` | `tests/test_stores.py`, `tests/test_script_mode.py::TestDurableResume` |
| `_script_tool.py` | `ScriptTool`: a saved script compiled at construction, its parameter and return schemas, `validate_input`, the `input.<field>` check | `tests/test_script_tool.py` |
| `_execute.py` | `Runner` (with `schedule`), `execute_plan`, `CallError`, `Suspend`, `Dispatch` | `tests/test_execute.py` |
| `_toolset.py` | `ScriptModeToolset(WrapperToolset)`, `run_script` description, catalog stash and `get_instructions`, dispatch, script tools served and run (`_ScriptToolsetTool`, `_call_script_tool`, `_run`) | `tests/test_script_mode.py` |
| `_capability.py` | `ScriptMode(AbstractCapability)`, discovery announcements | `tests/test_script_mode.py` |
| (composition) | `ScriptMode` under `TemporalDurability` and `DBOSDurability` | `tests/test_temporal.py`, `tests/test_dbos.py` (skip without the `durability` group); `tests/_shared_store.py` is the worker-global store one test passes through the sandbox |

Public surface is `pydantic_ai_scriptmode/__init__.py` (`__all__`).

How a task runs in script mode: the model gets one tool, `run_script`, whose description carries
the folded tools' signatures. It answers with one script. `ScriptModeToolset.call_tool` compiles it
to a plan, validates it against the signatures and `Limits`, and `execute_plan` drives the steps
through `_Dispatcher`, which calls each folded tool through a nested `ToolManager`. The model's
second request sees `{'status': ..., 'output': ...}` and writes the summary. A retry message
(compile, validate, or a failed step) costs one more request and settled steps are reused. A call
that needs approval parks the run; the approved re-run resumes from the record (ADR 0004). A saved
script is a script tool served by the same toolset with its own record (ADR 0005). The record
survives the process through `SQLiteRecordStore` (ADR 0006).

`examples/tutor.py` is a test harness first and an example second; the user intends to remove it
later, so nothing else may depend on it. It builds the same four tools into two agents, one with
plain tools and one with `ScriptMode`, runs each task on both, prints every script, retry, and
return, and ends with a comparison table (model requests, tool calls, total tokens).
`uv run python examples/tutor.py [task ...]`, tasks `practice`, `reviews`, `impossible`, `reset`
(the last needs approval for `reset_mastery`; the harness approves every request and continues);
`SCRIPTMODE_DYNAMIC_CATALOG=1` turns the flag on; the script agent has one script tool,
`weak_topics(threshold)`, folded by default, and `SCRIPTMODE_NATIVE_SCRIPTS=1` keeps it native.
Needs `ANTHROPIC_API_KEY` in `.env` (git-ignored, standard workspace key; an identity-linked key
needs an `anthropic-workspace-id` header the SDK does not add). All dependency groups are default
in `[tool.uv]`, so plain `uv sync` and `uv run` install the linters and the Anthropic extra.

`.local/` is git-ignored scratch holding the trial transcripts (`tutor-run-*.txt`,
`tutor-compare-*.txt`, `tutor-dynamic-*.txt`, `tutor-suspend-1.txt`, `tutor-scripttool-*.txt`);
anything else there is safe to delete.

## Decisions made while coding (not in the ADRs or README)

- Reuse rule is stricter than callscript: a settled step is reused only if name and hash match AND
  every step it references was also reused, and never if it reads `input`. Docstring on
  `reusable_steps` explains why.
- Sequential `await`s get `after` edges on call steps; derivations get none; a guard is a fence
  handled by `Runner.ready_steps`, not by edges.
- "Forgot `await`" is a compile-time heuristic: a bare call to a name that is neither a builtin nor a
  step defined earlier. Truly unknown functions are the validator's `unknown_function`.
- Fan-out bound must be a literal: `xs[:N]`, `xs[a:N]`, or a list display, on the fan-out or on the
  derivation a bare-name iterable was bound to (`_Compiler.bounds`). Anything else is
  `unbounded_for`. Only a direct derivation counts; `b = a` does not carry `a`'s bound.
- `try`/`except` accepts exactly one call statement and one recovery statement (`x = <expr>` to the
  same name, or `pass`). The error is bound to the `as` name as its message string.
- Anonymous steps are named `_callN` / `_guardN` by position.
- Tool exceptions, `ModelRetry`, argument `ValidationError`, and `ToolDenied` all become `CallError`
  so the script's error branch can catch them. `ApprovalRequired` is resolved inline or parks the
  run (ADR 0004, "Suspension" below); `CallDeferred` is resolved inline or is a `UserError`.
- Untyped tools have `return_schema == {}` (not `None`) in pydantic-ai 2.37, so the "no return
  schema" warning checks falsiness.
- The record is saved even when the run fails, so a retry reuses settled steps. The retry message
  names them.
- `Runner.schedule` is event-driven: in-flight steps are tasks keyed by name, one `asyncio.Event`
  (`woken`) set by every task's done callback wakes the loop on any settlement, and the settled tasks are
  read in launch order (dict order) and what became ready is launched. It was `asyncio.wait` with
  `FIRST_COMPLETED` until item 6: Temporal's workflow sandbox warns on `asyncio.wait` (its `done`
  set iterates in no fixed order; `UserWarning`, not a refusal, so under this suite's
  `filterwarnings = ['error']` it failed the workflow task, which Temporal retried forever, the
  hang below) and the engine runs workflow-side there. A halt gates new
  launches only, so in-flight steps settle and the record holds what their tools did. When
  `run_step` raises a `finally` cancels and awaits the remaining tasks so none outlives the run.
  Settled in review: only a `UserError` (unresolved deferral) or a bug can raise there, so the
  cancel is right. A suspension does not raise; it settles the step (see "Suspension" below).
- A fan-out gathers with `return_exceptions=True` so every item settles before the step does
  (`Runner.collect_items`). `_on_error='skip'` on a fan-out settles only the failed items to
  `None`; the step is `done` with a list. A whole-step skip (`skipped`, value `None`) is for a
  single call only. `try`/`except` does not accept a fan-out body.
- `CallDeferred` from a folded tool is resolved inline by `HandleDeferredToolCalls` through the
  nested `ToolManager`. Without a handler it is a `UserError` (`_Dispatcher`), as in harness
  `CodeMode`: the nested call is not one the model made, so its external result has no way back
  in. (Before ADR 0004 `ApprovalRequired` took the same path; it now parks the run.)
- A step value or the result may not hold a lambda or builtin reference, at any depth
  (`holds_function_value`). `to_jsonable_python` would otherwise serialize the closure's evaluator
  into the tool return and the record. Lambdas work inline (`sorted(xs, key=lambda ...)`).
- `+` and `*` on `str`/`list` charge the `NodeBudget` for the value they build. `range` charges
  before materializing. `OverflowError` and `RecursionError` are `EvalError`. `str.format` is
  refused because its field syntax reads attributes past the dunder guard; f-strings cover it.
- `unknown_function` is raised from two places with different details: the expression parser
  passes `name` only, the validator passes `name` and `step`. Its template uses only `name`. The
  parametrized test in `tests/test_teaching.py` catches templates that name an undocumented
  detail, but not one that a second raise site omits; check both sites when adding a kind.
- `tests/test_script_mode.py::test_validation_error_is_a_retry` asserts on rendered copy, not kind
  names. Kind names no longer appear in any model-facing text.
- `dynamic_catalog` (ADR 0003) mirrors harness `CodeMode` piece for piece. The catalog string is
  stashed on the toolset by `get_tools` and read by `get_instructions` in the same step;
  `for_run_step` copies it (and `_warned_no_return_schema`) onto a rebuilt instance because a
  dataclass `replace` re-runs `init=False` defaults. `get_instructions` relays upstream through
  `super()`, not `self.wrapped`, so a wrapped toolset's `id` stays on its own parts (found in review).
- The dynamic-mode description is byte-stable across discoveries by construction: the head, the
  limits, one pointer sentence that is true whether or not anything is folded yet, and a search
  addendum that depends only on whether `search_tools` is native. The end-to-end test asserts the
  description set has one element across a discovery.
- The announcement names tools as a script calls them (`sanitize_tool_name`, now package-public in
  `_toolset.py`), because the catalog shows the sanitized form.
- `_discovered_names` validates the search return leniently with two private `TypedDict`s, as the
  harness does: a malformed entry is skipped, a malformed catalog yields no names. The public
  `ToolSearchReturnContent` type would drop every name on one bad entry.
- `Record.to_dict` is `asdict` through `to_jsonable_python`, so a store never sees a `datetime`,
  tuple, or set (a custom `Dispatch` may settle one); a tuple comes back as a list. `from_dict` is
  strict by construction (`cls(**data)` raises `TypeError` on an unknown key). The shared fixture
  `parked_script_tool_record` in `tests/conftest.py` sets every field to a non-default; pyright
  strict refuses `from tests.test_x import ...`, so shared test data goes in `conftest.py`.
- `SQLiteRecordStore` owns a one-worker `ThreadPoolExecutor` and one connection opened by the
  first statement on that thread; `get`/`put` are `run_in_executor` calls and `close()` submits the
  connection close then `shutdown(wait=True)`. A connection per call would make `':memory:'` a
  fresh database every call; `asyncio.to_thread` plus a lock (the first cut) let `close()` run
  under a live statement, which segfaulted (the close-race test in `tests/test_stores.py` crashed
  the interpreter on the old code). `updated_at` is written by SQLite (`strftime(..., 'now')`), not
  Python, so it compares with `datetime('now', ...)`. `INSERT OR REPLACE`, not `ON CONFLICT`
  (SQLite 3.24). No WAL pragma. The test suite treats `ResourceWarning` as an error, so every
  store a test opens must be closed (the `store` fixture in `tests/test_stores.py` does it).
- `_run` skips the `put` for a script tool that completed from no record (`fresh_script_tool`),
  since the next call discards a completed record anyway; a failed, parked, or pre-existing record
  is still written. `SpyStore` in `tests/test_script_mode.py` pins it.
- Durability (item 6). Under `TemporalDurability` the `ScriptModeToolset` wraps the durable
  toolset (`outermost` ordering), so compile, validate, and schedule run in the workflow and every
  folded call is the wrapped toolset's activity (`agent__<name>__toolset__<id>__call_tool`); the
  history replays and a corrected script re-dispatches only the unsettled step
  (`tests/test_temporal.py`). The default in-memory record is rebuilt by replay, so it is the right
  store there, as long as it is workflow-scoped: the sandbox re-imports a module it does not pass
  through per workflow run, so a module-level `ScriptMode()` is fresh per run; a worker-global
  store plus a stable `conversation_id` would let a same-worker replay reuse the record and skip
  activities. Reproduced and pinned: `test_worker_global_store_diverges_on_replay` holds the store
  in `tests/_shared_store.py`, passed through the sandbox, and the in-process replay is a
  `NondeterminismError` (the default sandbox, two executions with the same conversation id on one
  worker, replayed cleanly). The README says to keep the store workflow-scoped. The engine-level
  answer, for the port, is to make the store's `get` and `put` durable operations
  (`@durable_operation` on the capability, `pydantic_ai.durable_exec`), so the journal carries the
  record across replays and workers; that is the "record on history" question ADR 0008 predicted
  and it is not decided yet (found in review); `SQLiteRecordStore` builds a thread pool, which the sandbox refuses at construction
  (pinned in `tests/test_temporal.py`), and the README says so. Under `DBOSDurability` the agent
  runs in the workflow function, `run_sync` works, and the model requests are the journaled steps
  (`tests/test_dbos.py`). Test facts: a DBOS app name is at most 30 characters; `run_sync` inside a
  DBOS workflow trips a `DeprecationWarning` from `pydantic_graph`'s `get_event_loop`, filtered per
  module since the suite errors on warnings; the Temporal dev server starts with
  `pydantic_graph` and `coverage` passed through the sandbox, on an ephemeral port (the client
  fixture connects to `temporal_env`'s address); a workflow that hangs is a workflow task failing
  and being retried forever, so every `execute_workflow` carries `execution_timeout=30s` and the
  failure is read with `-o log_cli=true -o log_cli_level=WARNING`. `uv run --group durability`
  adds the group to the shared venv and `uv run` never prunes, so after `make durability` a plain
  `make all` runs the durability tests too until the next `uv sync`.
- Suspension (ADR 0004). A parked step is in `settled` with status `suspended` but `Runner.bound`
  says it binds nothing, so its dependents and any guard after it never become ready; `schedule`
  returns instead of raising `PlanExecutionError` when pending steps remain and something is parked.
  A `Suspend` payload travels on `ExecuteResult.suspensions` as `(step, item index or None,
  payload)` and is never stored. `Runner.park` counts `suspend_attempts` on the record and turns the
  attempt past `max_suspend_attempts` into a `CallError` through `Runner.recover`, the same path as
  any failed call. A parked fan-out stores `ItemRecord`s (`done`, `skipped` with the error, or
  `suspended`); `Runner.gather_items` re-dispatches only the `suspended` items and hands the others
  back as their value or as a `CallError`, so `collect_items` treats reused and fresh items alike.
  `parked_steps` shares `reusable_steps`' rule (same hash, every read step reused, no `input`).
  A resolution reaches only a carried step (`step.name in Runner.carried`), and in a carried
  fan-out only its `suspended` items; a parked step whose inputs changed runs from scratch,
  unresolved, so nothing that never asked runs pre-approved (found by self-review, `1c9b299`).
  `Dispatch` is now a `Protocol` with a keyword `resolution`; `_Dispatcher` maps `resolution is
  True` to `handle_call(approved=True)` and `ApprovalRequired` to `Suspend({'tool', 'args',
  'metadata'})`. `call_tool` resumes when `ctx.tool_call_approved` and the record has suspended
  steps; it never reads `ctx.tool_call_metadata`. `CallDeferred` is still a `UserError`.

## Trial findings (real model, `anthropic:claude-opus-5`, one run each; not a benchmark)

The transcripts are in `.local/` (git-ignored), so these tables are the only durable record.

Plain tools against script mode, same model, same four tools (`.local/tutor-compare-*`):

| Task | Plain tools | Script mode |
| --- | --- | --- |
| practice | 4 requests, 12 calls, 1 retry, 7172 tokens | 3 requests, 12 calls, 1 retry, 8493 tokens |
| reviews | 4 requests, 14 calls, 6816 tokens | 2 requests, 14 calls, 4715 tokens |
| impossible | 3 requests, 9 calls, 4488 tokens | 2 requests, 9 calls, 4589 tokens |
| reset (approval) | 4 requests, 11 calls | 2 requests, one approval, only the two parked items re-dispatched |

Read it as: the model already parallelises calls it can see at once, so plain tools cost one
request per *dependent* stage, not per call; script mode collapses every stage into two requests.
Tokens are a wash at this size (the description is about 1.5k tokens); the saving grows with the
number of stages and with result size. `dynamic_catalog=True` matched the default after the review
fixes (2 requests, 0 retries on every task). With `weak_topics` folded the model called it in every
script, first time, with the right threshold; kept native, it called it from inside a script anyway
and paid one `unknown_function` retry, so the folded default is right.

What the model got wrong, and what fixed it: a non-Python comment marker on the intent line
(`« ... »`, `// ...`), fixed by the description's first bullet and a worked example starting with
`#`; `[:100]` on two fan-outs against a total of 200, fixed by raising `max_total_calls` to 500 and
saying the total counts every fan-out at its bound; a bound declared on a derivation one line above
the fan-out, fixed by backlog item 0. `unknown_tool` and `forgot_await` never fired. The teaching
copy recovered every rejection in one turn; no template was changed. The harness counts nested
calls from the `run_script` return's metadata, so a parked run's pre-park calls are not counted
(not fixed; the harness is temporary).

## Known and accepted (from the reviews; do not re-report)

- Non-string dict keys become strings through JSON, so a derivation's dict keyed by integers
  resumes with string keys under SQLite and integer keys in memory. The engine-level fix
  (JSON-shaping values in `Runner.settle`) would change first-run semantics for every user; the
  README and ADR say so instead. Revisit if a trial hits it.
- A `put` that fails after the tools ran (busy timeout, network filesystem) loses the outcome and
  the approval; the run fails and the model's next script re-runs the side effects. Infrastructure
  failure with no store to carry the outcome; the ADR names it.
- A deterministic saved script that fails for a transient reason raises `ModelRetry` each time and
  spends the script tool's `max_retries` (the ScriptMode value) before `UnexpectedModelBehavior`.
  ADR 0005 chose `ModelRetry` so the model can change the arguments; a `ToolFailed` would be the
  terminal alternative. Revisit if a trial shows a retry loop with unchanged arguments.
- Custom `RecordStore`s that parse the key as a UUID or constrain its charset break on a script
  tool's `conversation/name/digest` key. Documented in the README and the protocol docstring; no
  deprecation path, since the package has no release yet.
- Two concurrent calls of one script tool with identical arguments share a key and race on the
  record; if one parks and the other completes, the resumed one finds a completed record, ignores
  it, and raises the no-record `UserError`. Identical concurrent inputs are rare and the failure is
  loud. A per-call nonce in the key would fix it at the cost of resume across runs.
- The script tool key hashes `json.dumps(input, default=str)` while reuse compares with `==`, so
  `{'n': 1}` and `{'n': 1.0}` (JSON-schema parameters, no adapter) land in different records. Lost
  reuse only, never a wrong value.
- `run_script` scripts that read `input` (always `None`) are now reused like any step, where before
  they never were. Correct, and the retry copy lists them as settled.
- After a suspension only the resumed `run_script` returns, so its `ToolReturn` metadata holds the
  parts of the re-dispatched calls only; the calls made before the park are not in message
  history. The toolset is rebuilt per run and the record must hold data, so carrying parts across
  would mean serializing message parts into the record. The parked calls are in the approval
  request's metadata and every step's value is in the record; the README says so. Nested call ids
  restart at `__1` on the resumed run; the parking run's ids never reached history, so nothing
  collides.
- Under Temporal a worker-global record store plus a stable `conversation_id` diverges on replay
  (pinned, see "Durability" above); the default sandbox scopes a module-level store per execution.
  Whether the store should become a durable operation is decided at the port, not here.
- Two dependent approval-gated calls take two approval rounds: the second cannot start until the
  first resolves, so it parks on the resumed run. By design (a fence is a fence).
- A parked entry for a step no longer in any plan stays `suspended` in the record, with its count,
  until a script re-declares it. The record is the session.
- Announcement is not filtered through the fold rules: a discovered tool that `tools=[...]`
  excludes is still announced as callable from `run_script`. The capability has no tool
  definition at announce time. Same in the harness; the next catalog is the source of truth.
- Cross-run re-announce: `_announced_tools` starts empty on `for_run` and is not seeded from
  history, and `search_tools` returns already-discovered tools (undiscovered first), so a second
  run over the same history announces `weather` again. One sentence. `ctx.discovered_tool_names`
  is refreshed inside graph nodes, after `for_run`, so seeding there is unreliable.
- End-of-run redirect: an announcement enqueued after a response with no tool calls makes the
  drain redirect, costing one model request. Only native search can produce that shape.
- An inner capability that rewraps the `search_tools` result (into a `ToolReturn`, say) yields no
  names and so no announcement. Silent by design; the catalog still updates.
- The `for_run_step` copy of `_last_catalog` is redundant in the agent flow, where `ToolManager`
  calls `get_tools` right after the rebuild; it is kept for any caller that does not, and the
  harness test shape pins it.
- Cache claim scope: `dynamic=True` keeps the tools block and the static instructions cached; the
  catalog and everything after it are re-read on a discovery. The README says exactly that.
- `is_tool_call`: a bare call to a step name defined later in the script fires `forgot_await`
  rather than `unknown_function`. Both are rejections with teaching copy; the model fixes the line
  either way.
- Reuse after success: a later script in the same conversation that repeats a step by name and
  hash takes the recorded value instead of calling again, even after the earlier run succeeded.
  This is callscript's rule ("the record is the session") and the description tells the model.
  Revisit if the trial shows stale reads; the fix would be reusing only from an `error` record.
- Record not saved when a `UserError` escapes: that is a configuration error, not a model error,
  so no corrected script follows.
- `float('inf')` and `nan` survive as values; JSON encoding at the model boundary is pydantic's
  concern.
- `_Dispatcher.__call__` calls `to_jsonable_python` on each result and the tool return is
  serialized again on the way out. Double work on large results, no behaviour difference.

## Next session: start here

1. `cd pydantic-ai-scriptmode && git pull && uv sync --all-groups && make all`. Expect 236 passed
   (231 passed and 2 skipped without the `durability` group; `make durability` installs it) and a
   clean `git status`.
2. Process rules: an ADR before any backlog item (`docs/adr/000N-<slug>.md`, `status: proposed`,
   in the voice of `0002`: one paragraph of decision, one of cost, then the rejected options),
   grilled before the user's yes, then `mattpocock-skills:tdd` one commit per behaviour. Gate every
   commit on `make all` succeeding (`make all > log && echo MAKE_OK || exit 1`, then `git commit`);
   never chain a commit after a grep of the output. Before the ADR, grep the diff's nouns against
   `CONTEXT.md` and add any new term with an "Avoid" line. Run `code-review` at `medium` before
   the handoff; if it hits the session limit, retry once, then verify its candidate list by hand.
   Update this file in place at the end.
3. Item 6 is waiting on two actions that are the user's, in this order, and then on the
   maintainers. Ask whether they happened before doing anything else.
   - Publish 0.1.0 to PyPI: `uv build && uv publish` with a PyPI token the user holds; the name
     `pydantic-ai-scriptmode` was free on 2026-09-04 and `[project.urls]` is set. If the user
     would rather not, delete the `pip install` line from the issue draft.
   - Post `docs/upstream/issue.md` through the harness `Capability Request` template
     (<https://github.com/pydantic/pydantic-ai-harness/issues/new/choose>), one heading per field.
     Record the issue number here.
4. Until a maintainer answers, there is no port to do (ADR 0008). Things worth a session while
   waiting: the open Logfire finding in `examples/tutor.py` (above); a second trial run of the
   tutor tasks with the `Event` scheduler to confirm the comparison table still holds (the change
   is behaviour-preserving by the 33 engine tests, but the table is from the old loop); a Temporal
   test whose script fans out past `max_concurrency` and replays, since the two replaying tests run
   one activity at a time (review finding, not done); and the durable-operation store above, which
   needs an ADR amendment before code.

### Plan for the port, when a maintainer says yes

Everything below is decided in ADR 0008; the harness rules are in its `AGENTS.md`,
`agent_docs/capability-authoring.md`, `agent_docs/review-checklist.md`, and `agent_docs/docs-
conventions.md`. Fork `pydantic/pydantic-ai-harness` under the user's account, one branch, one PR
that links the issue.

- `pydantic_ai_harness/script_mode/`: `__init__.py` exporting `ScriptMode`, `ScriptTool`,
  `RecordStore`, `InMemoryRecordStore`, `SQLiteRecordStore`, `Limits`; `_capability.py` and
  `_toolset.py` as here; the engine modules as private siblings with imports rewritten. No
  dependency change, no extra.
- Root `pydantic_ai_harness/__init__.py`: `__all__`, the `TYPE_CHECKING` block, and the
  `__getattr__` dispatch; `tests/test_placeholder.py::test_all_exports_are_importable` enforces it.
- `pydantic_ai_harness/script_mode/README.md` (purpose-first lead, source link, spaced H1
  "Script Mode") and `docs/script-mode.md` registered in `tests/test_docs_parity.py::
  _CAPABILITY_PAGE_META`; the version-promise blockquote copied verbatim from `docs/code-mode.md`;
  the top-level `README.md` capability table under Context management; a partner PR to pydantic-ai's
  `docs/navigation.yml`.
- `tests/script_mode/`: this repository's tests with imports rewritten, `test_temporal.py` and
  `test_dbos.py` included; the harness suite does not error on warnings, so the DBOS filter can go.
  CI enforces 100% branch coverage, which this repository does not; expect to add cases.
- Harness writing style in every docstring and doc: no em-dashes, no superlatives, `--` for asides.
- After the merge: archive this repository with a README pointer; leave the PyPI release.

### Backlog after item 6

None recorded. Item 5 (JS surface) is closed by ADR 0007, not deferred.

## Reference repos (read-only siblings)

- `callscript/packages/callscript/src/` (`validate.ts`, `execute.ts`, `durable.ts`, `types.ts`)
  for behaviour to compare against.
- `pydantic-ai-harness/pydantic_ai_harness/code_mode/` for conventions; `AGENTS.md` and
  `agent_docs/capability-authoring.md` for the rules mirrored here.
- Installed `pydantic_ai` in `pydantic-ai-scriptmode/.venv` (2.37.0) for exact signatures.

## Verification commands

```bash
cd pydantic-ai-scriptmode
make all            # format, lint, typecheck, test
uv run pytest -q    # tests only
make durability     # Temporal and DBOS composition tests; installs the `durability` group
```

`timeout` is not available on this macOS shell; use a Python subprocess with a timeout if a test
run needs bounding. The test suite treats `ResourceWarning` as an error: close every store a test
opens.

## Suggested skills

Call these with the Skill tool at the step named.

- `mattpocock-skills:grilling`: on any new ADR before the user's yes, as on 0004 to 0008. Two
  rounds worked for 0006 and 0008: the frontier first, then what hung off the main choice.
- `mattpocock-skills:domain-modeling`: before the ADR, for any noun the diff adds.
- `mattpocock-skills:tdd`: every behaviour change; the seams are agreed in the build order.
- `mattpocock-skills:writing-for-agents`: when editing the `run_script` description, the grammar
  table, the announcement sentence, or the teaching copy; all are agent-facing prose.
- `code-review`: before the handoff, at `medium`, not `high` (`high` exhausted the session limit).
- `mattpocock-skills:handoff`: end of session. Its instruction is to write to a temp dir; the user
  has overridden that: update this file in place.
