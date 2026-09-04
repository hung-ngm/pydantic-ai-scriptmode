# Handoff: pydantic-ai-scriptmode

Date: 2026-09-05
Workspace: `/Users/hungng/Documents/AI/experiments/pydantic-experiments/`
Project: `pydantic-ai-scriptmode/`
This file is the single source of truth for progress. Update it in place at the end of each
session; no handoff copies elsewhere (no temp-directory copies, no progress in memory).

## Status

Complete as far as it can go without the user and the harness maintainers. Backlog items 0 to 4
are built (ADRs 0001 to 0006), item 5 was closed without code (ADR 0007), item 6 is decided (ADR
0008) and waits on the user. Four teaching examples landed on 2026-09-05 (`88251f9`..`776021d`).
Every item was built by TDD, one commit per behaviour, and pushed; `git log` is the record. `main`
is in sync with `origin`, nothing uncommitted. `make all` is green: 245 passed and 1 skip with the
`durability` group installed, 240 passed and 3 skips without it; no xfails.

Remote: `origin` is the private repo `https://github.com/hung-ngm/pydantic-ai-scriptmode`. Commit
straight to `main`, push after each commit, no force-push, no other branches.

## Next steps

Ask the user whether steps 1 and 2 happened before doing anything else.

1. **User: publish 0.1.0 to PyPI.** `uv build && uv publish` with a PyPI token the user holds. The
   name was free on 2026-09-04 and `[project.urls]` is set. If the user would rather not publish,
   delete the `pip install` line from `docs/upstream/issue.md`.
2. **User: post the capability-request issue.** `docs/upstream/issue.md` is written in the fields of
   the harness `Capability Request` template
   (<https://github.com/pydantic/pydantic-ai-harness/issues/new/choose>). Record the issue number
   here once posted.
3. **Wait for a maintainer.** ADR 0008: no port until the issue is answered. Worth a session while
   waiting, in this order:
   - A Temporal test whose script fans out past `max_concurrency` and replays; the two replaying
     tests run one activity at a time (review finding, not done).
   - An ADR amendment making the record store's `get`/`put` durable operations
     (`@durable_operation`, `pydantic_ai.durable_exec`), so the record rides on the journal instead
     of needing a workflow-scoped store. It is the "record on history" question ADR 0008 predicted
     and the first thing a harness reviewer will ask. Grill it before code.
   - Re-run `trials/tutor.py` to confirm the trial table below still holds with the `Event`
     scheduler (behaviour-preserving by the engine tests, but the table is from the old loop).
   - Optional, offered to the user, not asked for: a second prompt in `examples/script_tool.py`
     that the saved script cannot answer, so one output shows a script calling `restock_low` and
     one composing the primitives. Adds a fixed script to the test and a round trip when run live.
4. **When the answer is yes: the port.** Decided in ADR 0008; the harness rules are its `AGENTS.md`
   and `agent_docs/{capability-authoring,review-checklist,docs-conventions}.md`. Fork
   `pydantic/pydantic-ai-harness` under the user's account, one branch, one PR linking the issue.
   - `pydantic_ai_harness/script_mode/`: `__init__.py` exports `ScriptMode`, `ScriptTool`,
     `RecordStore`, `InMemoryRecordStore`, `SQLiteRecordStore`, `Limits`; `_capability.py` and
     `_toolset.py` as here; the engine modules as private siblings. No dependency change, no extra.
   - Root `pydantic_ai_harness/__init__.py`: `__all__`, the `TYPE_CHECKING` block, the
     `__getattr__` dispatch (`tests/test_placeholder.py::test_all_exports_are_importable`).
   - `script_mode/README.md` (purpose-first lead, source link, H1 "Script Mode") and
     `docs/script-mode.md` registered in `tests/test_docs_parity.py::_CAPABILITY_PAGE_META`, the
     version-promise blockquote copied from `docs/code-mode.md`, the top-level README table under
     Context management, and a partner PR to pydantic-ai's `docs/navigation.yml`.
   - `tests/script_mode/`: this repo's tests with imports rewritten, Temporal and DBOS included.
     The harness suite does not error on warnings (the DBOS filter can go) and enforces 100% branch
     coverage (expect to add cases). Harness writing style: no em-dashes, no superlatives.
   - The examples already fit the harness's `examples/` shape (`build_agent(model=)`, `main()`,
     `PYDANTIC_AI_MODEL`, construction test); carry one over if the maintainers want it.
   - After the merge: archive this repo with a README pointer; leave the PyPI release.

## Read first, in this order

- `README.md`: usage, how it works, grammar table, options, script tools, limits, `RecordStore`,
  durable execution, failure messages, engine-only use, examples.
- `CONTEXT.md`: the glossary. Use its words in code, docs, tests, and this file.
- `docs/adr/0001` to `0008`. Each ends with its rejected options; do not re-litigate them without
  new facts.
- `docs/upstream/issue.md`: the capability-request draft.
- Project memory `~/.claude/projects/-Users-hungng-Documents-AI-experiments-pydantic-experiments/memory/scriptmode-project.md`
  (loaded via `MEMORY.md`).

## Layout

`pydantic_ai_scriptmode/`, engine first, adapters last; every module docstring says what it owns.
Public surface is `__init__.py` (`__all__`).

| Module | Owns | Tests |
| --- | --- | --- |
| `_teaching.py` | `RejectionKind`, `TEACHING` table, `Issue`, `explain`, `issue` | `test_teaching.py` |
| `_expr.py` | expression subset: `parse_expression`, `free_names`, `Evaluator`, `NodeBudget` | `test_expr.py` |
| `_plan.py` | `CallStep`, `DeriveStep`, `GuardStep`, `Plan`, `Limits`, `step_hash` | via compile tests |
| `_compile.py` | `compile_script` -> `Plan` or `CompileError` (all issues at once) | `test_compile.py` |
| `_validate.py` | `validate_plan`, `ToolSignature` | `test_validate.py` |
| `_record.py` | `Record`, `StepRecord`, `ItemRecord`, `RecordStore` protocol, `InMemoryRecordStore`, `reusable_steps`, `parked_steps` | `test_record.py`, `test_execute.py::TestRecordReuse`, `::TestSuspend` |
| `_stores.py` | `SQLiteRecordStore(path, timeout=)`: one table, one owned thread and connection, `close()` | `test_stores.py`, `test_script_mode.py::TestDurableResume` |
| `_script_tool.py` | `ScriptTool`: a saved script compiled at construction, its schemas, `validate_input` | `test_script_tool.py` |
| `_execute.py` | `Runner` (`schedule`), `execute_plan`, `CallError`, `Suspend`, `Dispatch` | `test_execute.py` |
| `_toolset.py` | `ScriptModeToolset(WrapperToolset)`, `run_script` description, catalog stash and `get_instructions`, dispatch, script tools served and run | `test_script_mode.py` |
| `_capability.py` | `ScriptMode(AbstractCapability)`, discovery announcements | `test_script_mode.py` |
| (composition) | `ScriptMode` under `TemporalDurability` and `DBOSDurability` | `test_temporal.py`, `test_dbos.py` (skip without the `durability` group); `tests/_shared_store.py` is the worker-global store one test passes through the sandbox |
| `examples/` | `basic.py`, `script_tool.py`, `approval.py`, `engine.py`; `examples/README.md` is the table | `test_examples.py`: each built with `TestModel`, driven by a fixed script through `FunctionModel`, asserted on the fake store's state |
| `trials/tutor.py` | the measurement harness behind the trial table: four tasks, plain tools against `ScriptMode`, Logfire metrics. Nothing may depend on it | none |

How a run goes: the model gets one tool, `run_script`, whose description carries the folded tools'
signatures, and answers with one script. `call_tool` compiles it to a plan, validates it against the
signatures and `Limits`, and `execute_plan` drives the steps through `_Dispatcher`, which calls each
folded tool through a nested `ToolManager`. The model's next request sees `{'status', 'output'}`. A
retry (compile, validate, or a failed step) costs one more request and reuses settled steps. A call
needing approval parks the run and the approved re-run resumes from the record (ADR 0004). A saved
script is a script tool with its own record (ADR 0005). The record survives the process through
`SQLiteRecordStore` (ADR 0006).

Examples follow the harness's shape: `build_agent(model=DEFAULT_MODEL)` plus `main()`,
`PYDANTIC_AI_MODEL` overrides `anthropic:claude-sonnet-5`, `.env` via `load_dotenv`, in-memory data
returning dataclasses, the model's script printed next to its return. One domain per feature: issue
triage (fold, fan-out, guard), inventory (a saved `ScriptTool`), accounts payable (park on
`ApprovalRequired`, messages and request saved under `.local/approval/`, `--approve` resumes in a
new process through `SQLiteRecordStore`), weather (engine only). All four ran live on
`claude-sonnet-5` on 2026-09-05. `.env` holds `ANTHROPIC_API_KEY` (git-ignored; a standard
workspace key).

## Decisions made while coding (not in the ADRs or README)

Engine:

- Reuse is stricter than callscript: a settled step is reused only if name and hash match and every
  step it reads was also reused, and never if it reads `input` (docstring on `reusable_steps`).
- Sequential `await`s get `after` edges on call steps; derivations get none; a guard is a fence in
  `Runner.ready_steps`, not an edge.
- `Runner.schedule` is event-driven: in-flight steps are tasks; one `asyncio.Event` (`woken`), set
  by each task's done callback, wakes the loop, which reads settled tasks in launch order and
  launches what became ready. It replaced `asyncio.wait(FIRST_COMPLETED)`, which Temporal's sandbox
  warns on (a `UserWarning` that `filterwarnings = ['error']` turned into a workflow-task failure
  retried forever). A halt gates new launches only, so in-flight steps settle and the record holds
  what their tools did; when `run_step` raises, a `finally` cancels the rest.
- A fan-out gathers with `return_exceptions=True`; `_on_error='skip'` on a fan-out settles only the
  failed items to `None`. A whole-step skip is for a single call. `try`/`except` takes no fan-out.
- Fan-out bound must be a literal (`xs[:N]`, `xs[a:N]`, a list display), on the fan-out or on the
  derivation a bare name was bound to (`_Compiler.bounds`); `b = a` does not carry a bound.
- "Forgot `await`" is a compile-time heuristic (bare call to a name that is neither builtin nor an
  earlier step); unknown functions are the validator's `unknown_function`, raised from two sites
  with different details (check both when adding a kind).
- `try`/`except` accepts one call statement and one recovery (`x = <expr>` to the same name, or
  `pass`); the error binds to the `as` name as its message. Anonymous steps are `_callN`/`_guardN`.
- Tool exceptions, `ModelRetry`, argument `ValidationError`, and `ToolDenied` become `CallError`.
  `ApprovalRequired` parks the run; `CallDeferred` is resolved inline by `HandleDeferredToolCalls`
  or is a `UserError`, as in harness `CodeMode`.
- Values may not hold a lambda or builtin reference at any depth (`holds_function_value`); lambdas
  work inline. `+`/`*` on `str`/`list` and `range` charge the `NodeBudget`; `str.format` is refused
  (its field syntax reads past the dunder guard); `OverflowError`/`RecursionError` are `EvalError`.
- The record is saved even when the run fails; the retry message names the settled steps. Kind
  names never appear in model-facing text (`test_validation_error_is_a_retry` asserts on copy).
- Suspension (ADR 0004): a parked step is `settled` with status `suspended` but binds nothing, so
  dependents and later guards wait; `schedule` returns rather than raising when something is
  parked. `Runner.park` counts `suspend_attempts`; past `max_suspend_attempts` the park is a
  `CallError`. A parked fan-out stores `ItemRecord`s and only `suspended` items re-dispatch. A
  resolution reaches only a carried step with unchanged inputs, so nothing runs pre-approved that
  never asked. `Dispatch` is a `Protocol` with keyword `resolution`; `call_tool` resumes on
  `ctx.tool_call_approved` and never reads `ctx.tool_call_metadata`.

Records and stores:

- `Record.to_dict` is `asdict` through `to_jsonable_python` (a tuple comes back a list);
  `from_dict` is strict (`cls(**data)`). Shared test data lives in `tests/conftest.py`; pyright
  strict refuses `from tests.test_x import`, and a sibling test module is imported relatively.
- `SQLiteRecordStore` owns a one-worker `ThreadPoolExecutor` and one connection opened on that
  thread by the first statement; a connection per call would make `':memory:'` a fresh database
  each call, and `asyncio.to_thread` plus a lock let `close()` run under a live statement and
  segfault. `updated_at` is written by SQLite. `INSERT OR REPLACE`, no WAL pragma. The suite treats
  `ResourceWarning` as an error, so every store a test opens is closed.
- `_run` skips the `put` for a script tool that completed from no record (`SpyStore` pins it).

Toolset and capability:

- `dynamic_catalog` mirrors harness `CodeMode`: the catalog is stashed by `get_tools` and read by
  `get_instructions` in the same step; `for_run_step` copies it onto the rebuilt instance because
  `replace` re-runs `init=False` defaults; `get_instructions` relays through `super()`. The
  dynamic-mode description is byte-stable across discoveries by construction.
- Announcements name tools as a script calls them (`sanitize_tool_name`, package-public);
  `_discovered_names` validates the search return leniently, as the harness does.
- Untyped tools have `return_schema == {}` in pydantic-ai 2.37; the warning checks falsiness.

Durability (item 6):

- Under `TemporalDurability` the `ScriptModeToolset` wraps the durable toolset (`outermost`), so
  compile, validate, and schedule run in the workflow and every folded call is the wrapped
  toolset's activity (`agent__<name>__toolset__<id>__call_tool`); history replays, and a corrected
  script re-dispatches only the unsettled step.
- The in-memory record must be workflow-scoped. The default sandbox re-imports a module it does not
  pass through per execution, so a module-level `ScriptMode()` is fresh per run. A worker-global
  store plus a stable `conversation_id` lets a replay reuse the record, skip activities, and fail
  with `NondeterminismError`; pinned by `test_worker_global_store_diverges_on_replay` through
  `tests/_shared_store.py`. The engine-level answer is the durable-operation store in "Next steps".
- `SQLiteRecordStore` is refused at construction inside a workflow (its thread pool); pinned.
- Under `DBOSDurability` the agent runs in the workflow function, `run_sync` works, and model
  requests are the journaled steps. A DBOS app name is at most 30 characters; `run_sync` in a DBOS
  workflow trips a `DeprecationWarning` from `pydantic_graph`, filtered per module.
- Test mechanics: the Temporal dev server starts on an ephemeral port with `coverage` passed
  through; a hung workflow is a failing workflow task being retried, so every `execute_workflow`
  has `execution_timeout=30s` and the failure is read with `-o log_cli=true -o log_cli_level=WARNING`.
  `uv run --group durability` leaves the group installed, so `make all` runs the durability tests
  until the next `uv sync`; a plain `uv sync` prunes it and pyright then fails on `test_temporal.py`,
  so sync with `uv sync --group durability`.

Examples:

- Tools live on a module-level `FunctionToolset` (pyright strict flags nested tool functions as
  unused); `build_agent` returns `Agent[None, str]` with `deps_type=type(None)`. `result.usage` is a
  property in pydantic-ai 2.37.
- `approval.py` takes `store=` so a test and `main()` can close it; the default builds a
  `SQLiteRecordStore` under `STATE_DIR`, which the test monkeypatches. A resume needs the message
  history (it carries the `conversation_id` the record is keyed by), the `DeferredToolRequests`
  (round-trips through `TypeAdapter`), and the store.
- `zip` with tuple unpacking works in comprehensions of the expression subset.
- `test_examples_present` lists the files, so each example commit updated the list; the fixed
  scripts in the tests double as what a good script looks like.

## Trial findings (`anthropic:claude-opus-5`, one run each; not a benchmark)

Transcripts are in `.local/` (git-ignored), so this table is the durable record. Same four tools:

| Task | Plain tools | Script mode |
| --- | --- | --- |
| practice | 4 requests, 12 calls, 1 retry, 7172 tokens | 3 requests, 12 calls, 1 retry, 8493 tokens |
| reviews | 4 requests, 14 calls, 6816 tokens | 2 requests, 14 calls, 4715 tokens |
| impossible | 3 requests, 9 calls, 4488 tokens | 2 requests, 9 calls, 4589 tokens |
| reset (approval) | 4 requests, 11 calls | 2 requests, one approval, only the two parked items re-dispatched |

The model already parallelises calls it can see at once, so plain tools cost one request per
dependent stage; script mode collapses every stage into two requests. Tokens are a wash at this
size (the description is about 1.5k tokens). `dynamic_catalog=True` matched the default. A folded
script tool was called first time with the right argument; kept native, the model called it from a
script anyway and paid one retry, so the folded default is right. Every rejection was recovered in
one turn by the teaching copy; the fixes that came out of the trial were the description's first
bullet (a `#` intent line), `max_total_calls` 500 with the wording that every fan-out counts at its
bound, and backlog item 0.

## Known and accepted (from the reviews; do not re-report)

- Non-string dict keys become strings through JSON, so an integer-keyed dict resumes with string
  keys under SQLite. The engine-level fix would change first-run semantics; documented instead.
- A `put` that fails after the tools ran loses the outcome and the approval; infrastructure
  failure, named in ADR 0006.
- A saved script that fails transiently raises `ModelRetry` each time and spends `max_retries`
  before `UnexpectedModelBehavior` (ADR 0005 chose `ModelRetry`). Revisit on a retry loop with
  unchanged arguments.
- Custom stores that parse the key as a UUID break on a script tool's `conversation/name/digest`
  key; documented, no deprecation path before a release.
- Two concurrent calls of one script tool with identical arguments share a key; if one parks and
  the other completes, the resume raises the no-record `UserError`. Rare and loud.
- The script-tool key hashes `json.dumps(input, default=str)` while reuse compares with `==`, so
  `1` and `1.0` land in different records. Lost reuse only.
- After a suspension only the resumed `run_script` returns, so its metadata holds the re-dispatched
  parts only; pre-park calls are in the approval request's metadata and the record. Nested call
  ids restart at `__1` on the resumed run without colliding.
- Two dependent approval-gated calls take two approval rounds (a fence is a fence). A parked entry
  for a step no longer in any plan stays `suspended` until a script re-declares it.
- Reuse after success: a later script repeating a step by name and hash takes the recorded value
  (callscript's rule; the description says so). Revisit if a trial shows stale reads.
- Announcement is not filtered through the fold rules; cross-run re-announce of an already
  discovered tool costs one sentence; an announcement after a final response costs one redirect
  request; an inner capability that rewraps the search result yields no announcement.
- `dynamic=True` keeps the tools block and static instructions cached; the catalog and everything
  after it are re-read on a discovery.
- `is_tool_call`: a bare call to a step defined later fires `forgot_await`, not `unknown_function`.
- A record is not saved when a `UserError` escapes (a configuration error, no corrected script
  follows). `inf`/`nan` survive as values. `_Dispatcher` serializes each result twice; no
  behaviour difference.
- Under Temporal a worker-global store plus a stable `conversation_id` diverges on replay (pinned;
  "Durability" above). Whether the store becomes a durable operation is decided at the port.
- Models sometimes put work inside a `for` body on the first script (`approval.py` live run, two
  compile retries); the teaching copy recovers it. Not an example bug.

## Process rules

- An ADR before any backlog item (`docs/adr/000N-<slug>.md`, `status: proposed`, in the voice of
  `0002`: one paragraph of decision, one of cost, then the rejected options), grilled before the
  user's yes, then TDD one commit per behaviour. Examples and docs need no ADR.
- Gate every commit on `make all` succeeding (`make all > log && echo MAKE_OK || exit 1`, then
  `git commit`); never chain a commit after a grep of the output.
- Before an ADR, grep the diff's nouns against `CONTEXT.md` and add any new term with an "Avoid"
  line. Example domains are not glossary terms.
- Run `code-review` at `medium` before the handoff; if it hits the session limit, retry once, then
  verify the candidates by hand. Update this file in place at the end.
- Outward actions on pydantic's repos (issue, fork, PR) and the PyPI release are the user's; the
  agent drafts.
- Run an example live once after its offline test passes; it costs a few cents.

## Reference repos (read-only siblings)

- `callscript/packages/callscript/src/` (`validate.ts`, `execute.ts`, `durable.ts`, `js.ts`,
  `types.ts`) for behaviour to compare against.
- `pydantic-ai-harness/`: `pydantic_ai_harness/code_mode/` for conventions, `tests/code_mode/` for
  the durability test shape, `examples/` and `tests/test_examples.py` for the example shape,
  `AGENTS.md` and `agent_docs/` for the rules.
- Installed `pydantic_ai` 2.37.0 in `.venv` for exact signatures.

## Verification commands

```bash
cd pydantic-ai-scriptmode
make all                       # format, lint, typecheck, test
uv run pytest -q               # tests only
make durability                # Temporal and DBOS composition tests; installs the `durability` group
uv run examples/basic.py       # any example live; approval.py, then approval.py --approve
uv run trials/tutor.py         # the comparison harness, all four tasks
```

`timeout` is not available on this macOS shell; bound a run with a Python subprocess if needed.

## Suggested skills

- `mattpocock-skills:grilling`: on any new ADR or amendment before the user's yes (two rounds
  worked for 0006 and 0008: the frontier first, then what hung off the main choice; the examples
  took three, the third opened by a late "different use cases" ask).
- `mattpocock-skills:domain-modeling`: before an ADR, for any noun the diff adds.
- `mattpocock-skills:tdd`: every behaviour change; the seams are the public `Agent` path and the
  engine's `execute_plan`.
- `mattpocock-skills:writing-for-agents`: when editing the `run_script` description, the grammar
  table, the announcement sentence, or the teaching copy.
- `code-review`: before the handoff, at `medium`, not `high` (`high` exhausted the session limit).
- `mattpocock-skills:handoff`: end of session; the user has overridden its temp-dir instruction:
  update this file in place.
