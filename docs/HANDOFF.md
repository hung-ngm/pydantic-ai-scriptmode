# Handoff: pydantic-ai-scriptmode (durable record store done, reviewed, and pushed; next is backlog item 5)

Date: 2026-09-04
Workspace: `/Users/hungng/Documents/AI/experiments/pydantic-experiments/`
Project: `pydantic-ai-scriptmode/`
This file is the single source of truth for progress. Update it in place at the end of each
session; do not write handoff copies elsewhere (no temp-directory copies, no progress in memory).

## Where things stand

Backlog item 4, durable `RecordStore` (ADR 0006), is built by TDD, reviewed, committed, and
pushed. `make all` (ruff format, ruff check, pyright strict, pytest) is green: 231 passed, no
xfails, no skips. `git log` on `main`, newest first (handoff-only commits omitted):

- `7bc363e` Review fixes: the store owns one thread and one connection opened by the first statement, `close()` drains the queue; `INSERT OR REPLACE`; `updated_at` in SQLite's own text form
- `68d357a` Review fix: a script tool that completed from no record writes none, since the next call would discard it
- `2d07f99` Review fix: `from_dict` requires exactly the keys `to_dict` writes, since every field has a default and a dropped key loaded as a clean record
- `84e079c` ADR 0006: the lock is a threading lock in the worker thread (superseded by `7bc363e`)
- `b260953` Review fix: the store's lock is a `threading.Lock` taken in the worker thread (superseded by `7bc363e`)
- `692419b` README documents `SQLiteRecordStore`; the no-record error names it; ADR 0006 accepted
- `33d311d` End-to-end: a run parked in one agent resumes in another that shares only the SQLite file, for `run_script` and for a script tool
- `38b20f1` `SQLiteRecordStore`: one table on one held connection, statements in a thread under a lock; `':memory:'` works and a new store reads the file
- `3d3634d` `Record.to_dict` and `from_dict` round-trip a record through a JSON-safe object; the README store example uses them
- `879088f` ADR 0006 (proposed): durable record store, with Key in the glossary
- `23d2b06` Review fixes: a saved script over a tool that exists but is not available yet hides its script tool with a warning instead of failing the agent; JSON-schema parameters check the shape and `required` keys
- `29396ba` Review fix: a completed script tool call is not replayed from its record; only a failed or parked one resumes
- `ae4a65a` Review fix: the model's catalog folds only selected tools again; saved scripts see a quiet fold of every eligible tool, and an ambiguous or clashing name is a `UserError`
- `e715574` Review fix: the `input` field check covers the return line and does not count dict methods as fields
- `abdd7fb` Tutor harness: a `weak_topics` script tool; SCRIPTMODE_NATIVE_SCRIPTS=1 keeps it native; nested calls counted
- `1e91d06` README documents script tools; `RecordStore` is keyed by a string; ADR 0005 records `Record.input`
- `8a26c24` A script tool parks on an approval and resumes from its own record, called by the model or from a script
- `c030e35` Engine: the record keeps its `input`, and a step that reads `input` is reused or re-entered only under the same one
- `bab9512` A saved script is validated in `get_tools` against every eligible tool and the script tools before it; a bad name is a `UserError`
- `b7a6c17` A script tool's bad argument or failed step is a `ModelRetry` naming it; a script catches it as a `CallError`
- `e29dd9b` Pin: a script calls a folded script tool through the nested manager, and its parts nest in the metadata
- `019564d` A native script tool call runs the saved plan with the arguments as `input` and returns its output
- `f8f4032` Toolset serves script tools through the selector: folded into the catalog by default, native by predicate
- `7771c10` `ScriptTool` refuses a read of an `input` field its parameters do not declare
- `750a13b` `ScriptTool` renders `parameters` and `returns` as tool schemas and validates the arguments into `input`
- `0346a69` `ScriptTool` compiles its script at construction; description defaults to the intent
- `eda2934` Accept ADR 0005
- `ef394a3` ADR 0005 (proposed): script tools, with Script tool and Input in the glossary
- `3ee811f` Review fixes: an approval covers only the calls it was asked for; no record on resume is a `UserError`; a fan-out past the suspend limit keeps its done items; parks count only when surfaced; tool approval metadata passes through
- `1c9b299` Engine: a resolution reaches only the call or items the record parked; a re-run from scratch is unresolved
- `ab2d292` Tutor harness: `reset` task with an approval-gated tool; approvals are granted and the run continues
- `94ca65e` README documents suspension; `Suspend` and `ItemRecord` are public; ADR 0004 accepted
- `49618f1` `ScriptMode`: a call nothing approved inline parks the run; `run_script` raises `ApprovalRequired` and the approved re-run resumes from the record
- `092175a` Engine: `Limits.max_suspend_attempts`; a step that keeps parking fails with an error its branch can catch
- `f3a1356` Engine: `execute_plan(resolutions=...)` re-enters parked steps, re-dispatching only parked items; `Dispatch` takes `resolution`
- `348f3a3` Engine: a parked fan-out item keeps its done siblings as item records; an item error wins over a parked item
- `88350ea` Engine: a `Dispatch` may raise `Suspend`; the step parks, independent steps settle, the run is suspended
- `3a0fc05` ADR 0004 (proposed): suspend and detach, with Suspension and Resolution in the glossary
- `e2d9840` Description stays true before any tool is folded; search addendum when `search_tools` is native
- `7dbbe7b` Instruction tests compare content, since upstream text arrives normalized
- `b64acab` `get_instructions` relays upstream parts through the base class so owner keys survive
- `9a0e691` Announcement names discovered tools as a script calls them (sanitized)
- `8afc7e1` Glossary gains Discovery and Announcement; prose says discovered, not revealed
- `6ed2aee` README documents `dynamic_catalog`; tutor harness gets `SCRIPTMODE_DYNAMIC_CATALOG=1`
- `05f1e73` Test reads prompt parts by type so pyright strict passes
- `0458a58` End-to-end: a script calls a tool discovered by `ToolSearch` with `dynamic_catalog` on
- `1dab7b4` `ScriptMode` announces tools discovered by local or native search
- `3a55eb0` `ScriptMode(dynamic_catalog=True)` passes the flag through; `for_run` isolates state
- `6ddcd4e` Toolset carries the catalog stash through a per-step rebuild
- `448898e` Toolset surfaces the stashed catalog as a dynamic `InstructionPart`
- `f52fe14` Toolset splits the `run_script` description from the catalog behind `dynamic_catalog`
- `f02fbff` Accept ADR 0003
- `3c37bfa` ADR 0003 (proposed)
- `57517ff` Fan-out takes its bound from the derivation it iterates (backlog item 0)
- `1c87782` Tutor harness compares plain tools with script mode; all uv groups default
- `79468b8` Tune the run_script description from the first trial; total calls 500
- `35cbdd9` Tutor example and first real-model run; teach fan-out bound sizing
- `84047d8` Validator refuses a hand-built fan-out with no bound
- `69963e5` Unresolved approval inside a script is a UserError; dispatch is a class
- `d52d178` Fan-out waits for every item; skip is per item; no function-valued steps
- `9a95a74` Charge sequence growth, catch OverflowError, refuse str.format
- `79005aa` ScriptMode: inert-plan script mode for Pydantic AI

Remote: `origin` is the private repo `https://github.com/hung-ngm/pydantic-ai-scriptmode`;
`main` tracks `origin/main` and is in sync. Commit straight to `main` and push after each commit;
no force-push, no other branches yet.

Uncommitted, the user's own work in progress (do not touch, do not commit): Logfire instrumentation
of `examples/tutor.py` (`logfire.configure`, `instrument_pydantic_ai`, four metrics per run) with
`logfire>=4.41.0` added to the `examples` group in `pyproject.toml` and `uv.lock`. The harness
switch for `dynamic_catalog` (three lines) was committed out of that file by staging only its hunk;
the Logfire hunks remain unstaged. One review finding is for the user, not this package:
`logfire.configure()` runs at import with `send_to_logfire` defaulting to `True`, so a clone without
`logfire auth` or a token raises or prompts before `main()`; `send_to_logfire='if-token-present'`
(and `console=False` to keep the printed trace clean) would fix it.

Steps 1 to 4 are done. Backlog items 0 to 4 are done. The next item is 5, a JS surface, which
starts with an ADR; see "Next session".

Session history, newest first:

- 2026-09-04 (third part): backlog item 4. Read `_record.py`, `_toolset.py::_run`, and callscript's
  `durable.ts`; the finding that shaped the ADR is that a fresh `sqlite3` connection to `':memory:'`
  is a fresh database, so the store holds one connection for its life and serialises statements with
  a lock and `asyncio.to_thread`. Wrote ADR 0006, grilled it in two rounds (nine questions, then
  five on what hangs off SQLite; the user took every recommendation), built by TDD in four commits.
  The end-to-end test passed with no adapter change, since `_run` already read and wrote through the
  protocol. No trial: no model-facing copy changed and the test goes through the real
  `DeferredToolResults` path. `code-review` at `medium` hit the session limit on the first try and
  completed on the retry: ten findings, six fixed in four commits (one, the lock, was fixed by
  hand before the review returned and then superseded by its design finding), the rest accepted.
  See "Review findings". Then this file.
- 2026-09-04 (second part): backlog item 3. Read callscript's `engine.tool` (`engine.ts`, tested in
  `script-tool.test.ts`) and pydantic-ai's `ToolManager`; the finding that shaped the ADR is that
  `_raw_execute` dispatches through the manager's own toolset, so a saved script can reach folded
  tools only if `ScriptModeToolset` serves it. Wrote ADR 0005, grilled it (seven questions, the user
  took every recommendation), built by TDD in fourteen commits. Two things changed during the build:
  a saved script now sees every tool eligible for folding rather than only the folded ones (a test
  showed that making a tool native for the model would hide it from the developer's script), and
  the record gained `input` because the resume test parked again (a step reading `input` was never
  carried). Trialled twice on the tutor harness (see "Trial findings"). `code-review` at `medium` ran as three angle agents; their seventeen candidates were verified by
hand (the merged report had not arrived when the fixes were made): five fixed in four commits, the
rest accepted or the user's. See "Review findings". Then this file.
- 2026-09-04 (this file's state): the user's working copy of `examples/tutor.py` is the old HEAD
  plus the Logfire hunks, so it is now behind `HEAD` (it lacks `weak_topics`, the
  `SCRIPTMODE_NATIVE_SCRIPTS` switch, and `nested_calls`). To carry the Logfire hunks onto the
  new HEAD: `git diff 1e91d06 -- examples/tutor.py > /tmp/logfire.patch && git checkout
  examples/tutor.py && git apply --3way /tmp/logfire.patch`.
- 2026-09-03 (fourth part): wrote ADR 0004 after reading callscript's suspend path and pydantic-ai
  2.37's approval plumbing. Two facts changed the handoff's plan: `DeferredToolRequests.build_results`
  sends `metadata={}` unless the caller copies it, so `ctx.tool_call_metadata` cannot carry the
  resume, and a denied `run_script` is answered by Pydantic AI before the toolset sees it. Grilled the
  ADR (seven questions); the user took every recommendation. Built by TDD, one commit per behaviour.
  The auto-mode Bash classifier was down for some minutes mid-session; copy edits were done with the
  file tools meanwhile and committed once it returned. Trialled on the tutor harness with a new
  `reset` task (see "Trial findings"); the tutor hunk was staged from a HEAD copy so the user's
  Logfire hunks stayed uncommitted. `code-review` at `medium` hit the session limit once and
  completed on the retry after the limit reset: ten findings, seven fixed in `1c9b299` and
  `3ee811f`, the rest recorded under "Review findings".
- 2026-09-03 (third part): built `dynamic_catalog` by TDD in the order of the build plan,
  one commit per behaviour (`f52fe14` to `0458a58`). Domain-modeling pass added two glossary terms
  (`8afc7e1`). Trialled on the tutor harness with the flag on (see "Trial findings"). The
  `code-review` skill at `medium` hit the session rate limit mid-verification again; its fourteen
  candidates were verified by hand, three fixed (`9a0e691`, `b64acab`, `e2d9840`), the rest
  recorded under "Review findings". Two `make all` failures slipped into pushed commits because
  the commit was chained after an unchecked grep; fixed in follow-up commits (`05f1e73`,
  `7dbbe7b`), and every later commit is gated on `make all` succeeding.
- 2026-09-03 (second part): the user accepted ADR 0003 and asked for a build plan instead of
  starting the code.
- 2026-09-03: backlog item 0 done by TDD (`57517ff`): the compiler keeps `bounds`, the
  literal bound of every derivation, and a fan-out over a bare name inherits it; a rebinding drops
  it. Tests include the exact script from `.local/tutor-compare-2.txt`. README grammar paragraph
  updated; teaching copy unchanged, so no tutor run was needed. Wrote ADR 0003 for item 1 after
  reading harness `CodeMode.dynamic_catalog`.
- 2026-09-03 (later): step 3 done. Built `examples/tutor.py`, ran it five times against
  `anthropic:claude-opus-5` with the key from `.env` (git-ignored, standard workspace key; an
  identity-linked key needs an `anthropic-workspace-id` header the SDK does not add, which cost
  one detour). Tuned the description and one default from what the model got wrong. See "Trial
  findings" below.
- 2026-09-03: steps 1, 2, and 4 done, repo pushed. First commit, then a whole-package review. The
  `code-review` skill's multi-agent run hit the session rate limit mid-verification, so its merged
  candidate list was verified by hand in-line; every confirmed finding is a commit above. Wrote
  `.local/trial.py` for step 3. See "Review findings" below.
- 2026-09-02 (this session): filled the two former user slots, `Runner.schedule` in `_execute.py`
  and `TEACHING` in `_teaching.py`. Removed the three xfail marks. Excluded `.local/` from ruff and
  pyright in `pyproject.toml`. See "Decisions made while coding".
- 2026-09-02 (earlier): README reviewed against the code; grammar table, `Limits` table,
  `RecordStore` example, retry messages, engine-direct example. Every snippet was run.
- 2026-09-02 (first): design settled, package scaffolded, engine and adapters written with the two
  slots left empty for the user.

Read these first, in order. Do not restate them here.

- `README.md`: usage, "How it works", grammar table, options, retry messages.
- `CONTEXT.md`: glossary (19 terms). Use these words in code, docs, tests, and this file.
- `docs/adr/0001-*.md` to `0006-*.md`: why inert plan, why Python surface, why the catalog can
  move into instructions, why a parked call resumes from the record, why a saved script is a tool
  served by the toolset, why the package serializes the record and ships a SQLite store.
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
| `_stores.py` | `SQLiteRecordStore(path, timeout=)`: one table, one held connection, `close()` | `tests/test_stores.py`, `tests/test_script_mode.py::TestDurableResume` |
| `_script_tool.py` | `ScriptTool`: a saved script compiled at construction, its parameter and return schemas, `validate_input`, the `input.<field>` check | `tests/test_script_tool.py` |
| `_execute.py` | `Runner` (with `schedule`), `execute_plan`, `CallError`, `Suspend`, `Dispatch` | `tests/test_execute.py` |
| `_toolset.py` | `ScriptModeToolset(WrapperToolset)`, `run_script` description, catalog stash and `get_instructions`, dispatch, script tools served and run (`_ScriptToolsetTool`, `_call_script_tool`, `_run`) | `tests/test_script_mode.py` (`::TestScriptTools`, `::TestScriptToolSuspension`) |
| `_capability.py` | `ScriptMode(AbstractCapability)`, discovery announcements | `tests/test_script_mode.py` |

Public surface is `pydantic_ai_scriptmode/__init__.py` (`__all__`).

`examples/tutor.py` is a test harness first and an example second; the user intends to remove it
later, so nothing else may depend on it. It builds the same four tools into two agents, one with
plain tools and one with `ScriptMode`, runs each task on both, prints every script, retry, and
return, and ends with a comparison table (model requests, tool calls, total tokens).
`uv run python examples/tutor.py [task ...]`, tasks `practice`, `reviews`, `impossible`, `reset`
(the last needs approval for `reset_mastery`; the harness approves every request and continues);
`SCRIPTMODE_DYNAMIC_CATALOG=1` turns the flag on for the script agent. The script agent also has one
script tool, `weak_topics(threshold)`, folded by default; `SCRIPTMODE_NATIVE_SCRIPTS=1` keeps it
native. Nested calls are counted through script tools' metadata. Needs
`ANTHROPIC_API_KEY` in `.env` (git-ignored). All dependency groups are default in `[tool.uv]`, so
plain `uv sync` and `uv run` install the linters and the Anthropic extra together.

How a task runs in script mode: the model gets one tool, `run_script`, whose description carries
the four signatures. It answers with one script. `ScriptModeToolset.call_tool` compiles it to a
plan, validates it against the signatures and `Limits`, and `execute_plan` drives the steps
through `_Dispatcher`, which calls each folded tool through a nested `ToolManager`. The model's
second request sees `{'status': ..., 'output': ...}` and writes the summary. A retry message
(compile, validate, or a failed step) costs one more request and settled steps are reused.

`.local/` is git-ignored scratch: `tutor-run-1.txt` to `tutor-run-5.txt`, `tutor-compare-*.txt`, and
`tutor-dynamic-*.txt` are the trial transcripts;
the scheduler answer key and swap helper from the learning phase are redundant and safe to delete.

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
- `Runner.schedule` is event-driven: in-flight steps are tasks keyed by name, `asyncio.wait`
  with `FIRST_COMPLETED` wakes on any settlement and launches what became ready. A halt gates new
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

## Review findings (step 2, done 2026-09-03)

Durable store review (2026-09-04, `code-review` at `medium`, twelve verifiers, ten findings).
Fixed: `close()` closed the connection under a running `to_thread` statement, a reproducible
segfault or a lost parked record; the constructor opened the file and ran the DDL on the loop
with the busy timeout in force; a fan-out of `put`s parked one default-executor thread per caller
(`7bc363e`: the store owns one thread, opens lazily on it, and `close()` drains it); `ON CONFLICT`
needs SQLite 3.24 (`7bc363e`: `INSERT OR REPLACE`); `updated_at` in Python `isoformat()` did not
compare with SQLite's `datetime()` (`7bc363e`: written by SQLite in its own form; README prune
query fixed); `from_dict` was strict on unknown keys only, and every field has a default, so a
dropped key loaded as a clean record (`2d07f99`); a completed script tool's record was written and
never read (`68d357a`); the ADR claimed `to_dict` on the nested classes and two `UserError`s naming
the store (ADR corrected with the copy). Accepted, below.

- Non-string dict keys become strings through JSON, so a derivation's dict keyed by integers
  resumes with string keys under SQLite and integer keys in memory. The engine-level fix
  (JSON-shaping values in `Runner.settle`) would change first-run semantics for every user; the
  README and ADR say so instead. Revisit if a trial hits it.
- A `put` that fails after the tools ran (busy timeout, network filesystem) loses the outcome and
  the approval; the run fails and the model's next script re-runs the side effects. Infrastructure
  failure with no store to carry the outcome; the ADR names it.

Script tools review (2026-09-04, `code-review` at `medium`, three angle agents, seventeen
candidates verified by hand). Fixed: `input_fields` skipped the `return` expression and counted
`input.get`/`keys`/`items`/`values` as fields (`e715574`); folding every eligible tool for the
model's catalog let a native-by-selector tool hide a folded tool with the same sanitized name, made
the reserved-name error and the no-return-schema warning fire for native tools, and let a script
tool named like a wrapped tool's sanitized name be silently dropped and its calls routed to the
wrapped tool (`ae4a65a`: the loud fold is over the folded set again, saved scripts get a quiet
fold of every eligible tool in which a collision drops both sides and is a `UserError` if a saved
script calls it, and a script tool named like a wrapped tool's sanitized name is a `UserError`); a
script tool called again with the same arguments in a conversation replayed its record and ran no
tool (`29396ba`: a completed record is ignored; a failed or parked one is a retry or resume); a
saved script over a `ToolSearch` tool not yet discovered raised from `get_tools` on every run
(`23d2b06`: a known but unavailable tool hides the script tool for the step with one warning; an
unknown name still raises; a hidden script tool is unavailable to later saved scripts); JSON-schema
`parameters` were never checked, so a missing argument surfaced as a step failure (`23d2b06`:
object shape and `required` keys are checked, types are not, and `InputError` becomes `ModelRetry`).
Two candidates were about the user's Logfire work (see "Where things stand"). Accepted, below.

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

Fixed, one commit each, listed under "Where things stand". The four candidates the previous
session named resolved as: (1) `call_tool` split into `_Dispatcher` and `_execution_retry`; the
compile and validate retries share `_render_issues`, the execution retry is a different shape and
stays separate. (2) `_call_builtin` charges consistently; the real bypass was `*` and `+` on
sequences, now charged. (3) Cancel is right; see "Decisions". (4) Accepted, below.

`dynamic_catalog` review (2026-09-03, `code-review` at `medium`, verified by hand after the rate
limit): fourteen candidates. Fixed: announcement used raw names where the catalog shows sanitized
ones (`9a0e691`); `get_instructions` called `self.wrapped` directly, which the base class treats as
"authors its own instructions" and so dropped the upstream toolset's owner key on the direct-wrap
path (`b64acab`, confirmed by a verifier against `toolsets/abstract.py`); with nothing folded yet
the description pointed at a catalog that was not there and the head said "listed below"
(`e2d9840`). Two candidates were about the user's uncommitted Logfire work (see "Where things
stand"). The rest are accepted below.

Suspend and detach review (2026-09-04, `code-review` at `medium`, completed): ten findings.
Fixed: a stale parked step from a denied script ran approved on a later script's approval
(resolutions are now scoped to `Record.parked`, the steps the parking run surfaced); an approved
re-run with no record silently re-ran every settled step and re-parked forever (now a `UserError`);
a fan-out past `max_suspend_attempts` went through `recover` and lost its done items (now only the
parked items fail and `collect_items` settles the rest); a park counted toward the limit in a run
that ended in error and so asked nobody (counts commit only when the run surfaces the suspension);
the count carried to a rewritten step with the same name (gated on `carried`); a stored count for a
step absent from `steps` raised `KeyError` (guarded); the nested tool's own `ApprovalRequired`
metadata was dropped from the approver's view (passed through as `metadata`); `parked_steps` took
the `reused` dict instead of recomputing it; stale `UserError` prose in this file, the README, and
the `schedule` docstring. Accepted, below.

Known and accepted:

- After a suspension only the resumed `run_script` returns, so its `ToolReturn` metadata holds the
  parts of the re-dispatched calls only; the calls made before the park are not in message
  history. The toolset is rebuilt per run and the record must hold data, so carrying parts across
  would mean serializing message parts into the record. The parked calls are in the approval
  request's metadata and every step's value is in the record; the README says so. Nested call ids
  restart at `__1` on the resumed run; the parking run's ids never reached history, so nothing
  collides.
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

1. `cd pydantic-ai-scriptmode && git pull && uv sync --all-groups && make all`. Expect 227 passed.
   `git status` will show the user's uncommitted Logfire work (see above); leave it. To commit a
   change to `examples/tutor.py` without those hunks, apply the change to a copy of
   `git show HEAD:examples/tutor.py`, `git hash-object -w` the copy, and
   `git update-index --cacheinfo 100644,<sha>,examples/tutor.py`, as this session did.
2. Backlog item 5, a JS surface: a second front end compiling to the same `Plan`. ADR first
   (`docs/adr/0007-js-surface.md`), grill it, code only after the user's yes. ADR 0002 rejected a
   JS surface for v1 (no maintained JS parser in Python; a second dialect next to `CodeMode`), so
   the ADR must answer that first: whether the case has changed, which parser (a hand-written
   parser for the subset, or none), and whether `run_script` grows a `language` argument or a second
   tool. Read callscript's `validate.ts` and `types.ts` for the grammar it accepts, and
   `_compile.py` for what a front end must produce (`Plan`, `bounds`, `step_hash` inputs). It is
   also fair to recommend against the item, since 0002's reasons still hold; the user decides.
3. Process rule: gate every commit on `make all` succeeding
   (`make all > log && echo MAKE_OK || exit 1`, then `git commit`). Never chain a commit after a
   grep of the output. Run `code-review` at `medium`; if it hits the rate limit, verify its
   candidate list by hand.

### Plan for item 4: durable `RecordStore` (done 2026-09-04; kept for the record)

Goal, in glossary terms: a record survives the process. Today `InMemoryRecordStore` is a dict, so a
run that parks in one process cannot resume in another, and two `UserError`s in `_toolset.py` say
so. The protocol (`get(key)`, `put(key, record)`) already admits any backend; the README shows a
hand-rolled Redis store. The item ships one durable store in the package and makes writing another
trivial.

Read first, in this order, and do not restate them in the ADR:

- `pydantic_ai_scriptmode/_record.py`: `Record` (`steps`, `status`, `at`, `output`,
  `suspend_attempts`, `parked`, `input`), `StepRecord` (`items` of `ItemRecord`), the protocol, and
  the in-memory store. Every field is plain data; `dataclasses.asdict` round-trips it, and the
  README "RecordStore" example is the deserializer written by hand.
- `_toolset.py::_run` (the one place that reads and writes a record: get, execute, put, then raise on
  a suspension) and `_script_tool_key` (a script tool's key is `conversation/name/digest`; a
  `run_script` key is the conversation id, a UUID7 string from `ctx.conversation_id`).
- `callscript/packages/callscript/src/durable.ts` (whole file, about 300 lines) and
  `durable.test.ts`. callscript's durable runner stores a *run* (`StoredRun`: id, owner, script
  hash, state, status, suspensions, resolutions, revision, timestamps, expiry) behind a four-call
  storage contract whose floor is `compareAndSet` on a revision, plus a scheduler. Ours stores a
  record per key with no revision; the ADR says which of those to take.
- pydantic-ai has no store of its own to mirror; `pydantic_ai.durable_exec` is Temporal, DBOS, and Prefect
  integration, and the toolset's Temporal error already says `run_script` must be an activity.

What the ADR (`docs/adr/0006-durable-record-store.md`, `status: proposed`, voice of `0002`) must
decide. Give a recommendation for each; `mattpocock-skills:grilling` on the ADR before the user's yes:

- Serialization owned by the package. Recommended: `Record.to_dict()` and `Record.from_dict()`
  (classmethods on `Record`, `StepRecord`, `ItemRecord`), so a store only moves a JSON object and
  the README example shrinks to two lines. This is the first commit whatever the backend.
- Backend. Recommended: SQLite through the standard library `sqlite3`, one table
  `records(key TEXT PRIMARY KEY, record TEXT, updated_at TEXT)`, calls run in
  `asyncio.to_thread` so the loop is not blocked and no dependency is added; a JSON-file-per-key
  store is the alternative (no dependency either, but a key with slashes needs hashing or nested
  directories, and atomic replace is per file). Name it `SQLiteRecordStore(path)`; `':memory:'`
  gives a test double without the dict store.
- Where it lives. Recommended: `pydantic_ai_scriptmode/_stores.py`, exported from `__init__`; no
  optional extra, since `sqlite3` is stdlib.
- Concurrency. Today `put` is last-write-wins and `run_script` is `sequential=True`, so the only
  race is two script tool calls with identical arguments (accepted in the item 3 review).
  Recommended: keep the protocol as is and document last-write-wins; callscript's revision CAS is
  a protocol change (`put` would answer whether it won) that nothing here needs yet. Record the
  option so it is not re-litigated.
- Retention. Recommended: none in the package; a `delete(key)` is not in the protocol and the
  README says how to prune by `updated_at`. Decide whether `updated_at` is worth a column for that.
- Cross-process resume test shape. Two `ScriptModeToolset`s (or two agents) sharing one store
  path, the first parks, the second resumes from `message_history` with the approval. That is the
  behaviour the item exists for and must be a test, not a trial.

Build order after the yes, `mattpocock-skills:tdd`, one commit per behaviour:

1. `Record.to_dict`/`from_dict` round-trip, including a suspended fan-out with `items` and a
   script tool record with `input`; the README Redis example rewritten on them (`tests/test_execute.py`
   or a new `tests/test_record.py`).
2. `SQLiteRecordStore`: `get` on a missing key is `None`; `put` then `get` round-trips; a second
   `put` replaces; the file is created on first use; `':memory:'` works (`tests/test_stores.py`).
3. End-to-end: park in one agent, resume in another sharing the store (`tests/test_script_mode.py`,
   next to `TestScriptToolSuspension`), for `run_script` and for a script tool.
4. Copy: README options table (`record_store` names the shipped store), "RecordStore" section,
   the two `UserError`s in `_toolset.py` that mention the in-memory store; ADR `accepted`; this file.
5. Trial: optional. No model-facing copy changes, so run the tutor `reset` task once with the
   SQLite store behind both runs only if step 3 leaves doubt about the real `DeferredToolResults`
   path; save as `.local/tutor-durable-1.txt` if run. Then `code-review` at `medium`.

### Plan for item 2: suspend and detach (done 2026-09-03; kept for the record)

Goal, in glossary terms: a call that needs an approval parks the run instead of failing it. The
record keeps every step that settled, the run's status is `suspended`, and the next `run_script`
resumes from the record with only the parked call re-dispatched, now approved. This replaces the
`UserError` path in `_Dispatcher` for `ApprovalRequired`; `CallDeferred` (external execution) is
out of scope unless the ADR argues otherwise.

Read first, in this order, and do not restate them in the ADR:

- `callscript/packages/callscript/src/execute.ts` lines 60 to 80 (`SuspendSignal` contract) and
  505 to 615 (how suspensions are collected across concurrent steps, `suspendedResult`);
  `types.ts` lines 360 to 490 (`ItemStatus`, `StepStatus`, `RunState.status`, `ExecuteResult`
  union, `resolutions`, `maxSuspendAttempts`).
- `pydantic_ai_scriptmode/_execute.py` (`ExecuteResult`, `Runner.settle`, the halt in
  `Runner.schedule`) and `_record.py` (`StepStatus`, `RunStatus`, `reusable_steps`). Today a step
  is one of `done`, `skipped`, `error`, `returned`; a run is `done`, `returned`, `error`.
- `_toolset.py`: `_Dispatcher.__call__` (the `UserError` raise), `call_tool` (where the record is
  loaded and saved), and `tests/test_script_mode.py::test_approval_is_resolved_inline_or_is_a_user_error`.
- pydantic-ai 2.37 surfaces the mechanism needs, all verified this session:
  `ApprovalRequired(metadata=...)` in `exceptions.py` line 168; the metadata returns as
  `ctx.tool_call_metadata` when the agent re-runs the approved tool with
  `ctx.tool_call_approved=True` (`tool_manager.py` lines 290 to 305); the nested
  `ToolManager.handle_call(part, approved=..., metadata=...)` at line 1030 can mark one nested
  call approved. `DeferredToolResults` and `Agent.run(deferred_tool_results=...)` are the user's
  resume surface (`agent/__init__.py` line 1181).

What the ADR (`docs/adr/0004-suspend-and-detach.md`, `status: proposed`, voice of `0002`) must
decide. Give a recommendation for each; `mattpocock-skills:grilling` on the ADR before the user's yes:

- Shape of the suspension. Recommended: `run_script` raises `ApprovalRequired` with metadata
  holding the parked step names, their nested call ids and arguments, and the `_reason` if the
  script gave one, so the approver sees what will run. The record is saved before raising with
  run status `suspended` and the step status `suspended` (a new `StepStatus`, mirroring callscript;
  a fan-out item can be `suspended` too).
- Resume. Recommended: on the approved re-run, `call_tool` reads `ctx.tool_call_metadata`,
  compiles the same script (the model does not write a new one; the agent re-issues the approved
  `run_script` call with the same arguments), and `execute_plan` re-dispatches only the
  `suspended` steps with `approved=True` on the nested `handle_call`. `reusable_steps` must treat
  `suspended` as a re-entry point, not a reusable step. A denied approval settles the parked step
  as an `error` that the script's error branch can catch, as `ToolDenied` does today.
- Concurrency. A halt gates new launches only (see "Decisions"), so in-flight siblings settle
  before the run parks; the record must hold them. Several steps may park in one run; the
  metadata lists all of them and one approval resumes all (callscript collects `suspensions`
  across steps). Decide whether partial approval is allowed; recommended no, for the first cut.
- Retry budget. A suspension is not a model error: it must not consume `max_retries`, and the
  retry message path (`_execution_retry`) must not fire. Also decide a `max_suspend_attempts`
  guard like callscript's, so a tool that keeps asking cannot loop; recommended a `Limits` field.
- Interaction with `HandleDeferredToolCalls`. Today it resolves approvals inline through the
  nested manager, and that stays the fast path. The ADR says which wins when both are present;
  recommended inline first, park only if nothing resolved it.
- Teaching copy. The description gets one sentence: a call that needs approval pauses the script
  and the same script continues once approved; do not rewrite it. `_teaching.py` may need no new
  kind. `CONTEXT.md` needs **Suspension** (a parked call waiting on an approval; avoid: pause,
  deferral, interrupt) and possibly **Resume**; run `mattpocock-skills:domain-modeling` on the ADR.

Build order after the yes, `mattpocock-skills:tdd`, one commit per behaviour, in
`tests/test_execute.py` for the engine and `tests/test_script_mode.py` for the adapter:

1. Engine: a `Dispatch` may raise a new `Suspend` exception; the step settles `suspended`, the
   run halts new launches, siblings settle, `ExecuteResult.status == 'suspended'` with the parked
   step names. `reusable_steps` skips `suspended`.
2. Engine: `execute_plan(..., resolutions=...)` re-dispatches parked steps with the resolution
   passed to `Dispatch`, and everything else is reused from the record.
3. Adapter: `_Dispatcher` turns `ApprovalRequired` into `Suspend` carrying the nested call part;
   `call_tool` saves the record and raises `ApprovalRequired(metadata=...)` from `run_script`.
4. Adapter: the approved re-run resumes through `ctx.tool_call_metadata`; denial settles the step
   as an error. End-to-end tests with `Agent.run(deferred_tool_results=...)`, both approve and
   deny, and one with a fan-out where one item parks.
5. Copy: README ("How it works" gets one paragraph, options table if a limit was added), the
   description sentence, the ADR marked `accepted`, this file.
6. Trial: add a task to `examples/tutor.py` whose tool raises `ApprovalRequired` unless approved,
   run with the key from `.env`, save the transcript as `.local/tutor-suspend-1.txt`, record the
   result under "Trial findings". Then `code-review` at `medium`, then update this file.

## Next steps, in order

Each step says what to do, what "done" looks like, and what to write back here.

### 3. First real-model trial (done 2026-09-03)

Provider and model: Anthropic, `claude-opus-5`, through `Agent('anthropic:claude-opus-5')` with
the key loaded by `python-dotenv` from `.env`. Harness: `examples/tutor.py`, tasks `practice`
(fan-out, filter, second fan-out with `_on_error='skip'` over a tool that fails for one topic),
`reviews` (fan-out, guard, side-effecting fan-out), `impossible` (no tool can do it).

Turns to success, before and after tuning:

| Task | Run 1 | Run 5 (after) |
| --- | --- | --- |
| practice | 1 script, 0 retries | 1 script, 0 retries |
| reviews | 3 scripts, 2 retries | 1 script, 0 retries |
| impossible | 1 script, 0 retries | 1 script, 0 retries |

Rejection kinds that fired, by frequency, across runs 1 to 4 (all on the `reviews` task):

1. `syntax_error` on line 1, three times: the intent line was `« ... »`, `« # ...`, then `// ...`.
   The model reaches for a non-Python comment marker on the first line only. The copy recovered
   it in one turn every time. Fixed up front by the description's first bullet: "a Python `#`
   comment ... never `//` or quotes" and a worked example that starts with `#`.
2. `too_many_calls`, three times: `[:100]` on both fan-outs plus one call is 201 against 200.
   The copy recovered it in one turn (the model went to `[:80]`). Two rounds of description
   wording ("pick N as what you expect") did not change the first script; the model anchors on
   the per-fan-out limit. Fixed by raising `Limits.max_total_calls` to 500 and stating in the
   limits sentence that the total counts every fan-out at its bound.

Not observed: `unknown_tool` (the impossible task never called a missing tool; the model gathered
what it could and said it had no email tool), `forgot_await`, stale reuse across tasks (the three
tasks use different step names, so nothing was reused). The teaching copy did its job every time
it fired; no template was changed.

Plain tools against script mode, same model, same tools, one run each (`.local/tutor-compare-*`):

| Task | Plain tools | Script mode |
| --- | --- | --- |
| practice | 4 requests, 12 calls, 1 retry, 7172 tokens | 3 requests, 12 calls, 1 retry, 8493 tokens |
| reviews | 4 requests, 14 calls, 6816 tokens | 2 requests, 14 calls, 4715 tokens |
| impossible | 3 requests, 9 calls, 4488 tokens | 2 requests, 9 calls, 4589 tokens |

Read it as: the model already parallelises calls it can see at once (eight `get_mastery` in one
response), so plain tools cost one request per *dependent* stage, not per call. Script mode
collapses every stage into two requests. Tokens are a wash at this size (the description is about
1.5k tokens and the results are small); the saving grows with the number of stages and with result
size, since intermediate results never enter the model's context. Do not quote these numbers as a
benchmark; one run each, and the practice row includes a retry on each side.

Two more findings from the comparison run:

- `unbounded_for` fired once: the model wrote `target = weak[:3]` and then fanned out over
  `target`. The bound was declared, one line up, on a derivation; the compiler wants the literal on
  the fan-out's own iterable. Recovered in one retry (`target[:3]`). Candidate for a small
  compiler change, listed under step 5.
- A plain tool exception ends a pydantic-ai run outright; the plain agent crashed on the first
  practice run until `fetch_exercises` raised `ModelRetry`. Script mode had already turned the
  same exception into a `CallError` the script's `_on_error='skip'` handled. That is a real
  difference in failure handling, not a comparison artefact, but the harness now raises
  `ModelRetry` so both sides can recover.

`dynamic_catalog=True` on the same harness (2026-09-03, `.local/tutor-dynamic-1.txt`, before the
review fixes to the description; `-2.txt` after them). The harness has no `ToolSearch`, so this
checks that the catalog in the instructions teaches as well as the catalog in the description:

| Task | Run 1 (flag on) | Run 2 (flag on, after review fixes) |
| --- | --- | --- |
| practice | 3 requests, 12 calls, 0 retries, 7517 tokens | 2 requests, 12 calls, 0 retries, 5115 tokens |
| reviews | 2 requests, 14 calls, 0 retries, 4591 tokens | 2 requests, 14 calls, 0 retries, 4547 tokens |
| impossible | 2 requests, 9 calls, 0 retries, 4603 tokens | 2 requests, 9 calls, 0 retries, 5048 tokens |

No rejection fired in either run; run 2 matches run 5 with the default. In run 1 the practice
task took a third request by the model's choice, not a retry: it wrote one script that returned
topics and mastery, then a second that fanned out `fetch_exercises` over a literal list of the
three weak topic ids. One run each, so read that as variance, not as a cost of the flag.

Suspend and detach (2026-09-03, `.local/tutor-suspend-1.txt`, task `reset`: reset mastery for every
topic below 0.5, where `reset_mastery` needs approval). One run each:

| Agent | Requests | Calls | What happened |
| --- | --- | --- | --- |
| plain tools | 4 | 11 | two `reset_mastery` calls deferred, approved, re-run |
| script mode | 2 | 2 (see note) | one script; fan-out `resets` parked at items 0 and 1; one approval; only those two re-dispatched |

The model wrote the script first time with no retry, put `_reason='score below 0.5'` on the
parked call without being asked, and did not rewrite the script after approval (Pydantic AI
re-issues the call, so the model never gets the chance; the description sentence is for the
denial case). The approval metadata read as intended: intent plus the two parked items with tool,
arguments, and reason. Note on the call count: the harness counts nested calls from the
`run_script` return's metadata, and the parked `run_script` has no return, so the nine calls made
before the park (one `list_topics`, eight `get_mastery`) are not counted; the true total is 11,
the same as plain tools. Not fixed, since the harness is temporary.

Script tools (2026-09-04, `.local/tutor-scripttool-1.txt` with `weak_topics` folded, `-2.txt` with
it native; tasks `practice`, `reviews`, `reset`). One run each:

| Task | Plain tools | Script mode, `weak_topics` folded | Script mode, `weak_topics` native |
| --- | --- | --- | --- |
| practice | 4 req, 12 calls, 1 retry | 2 req, 13 calls, 0 retries | 3 req, 12 calls, 1 retry |
| reviews | 4 req, 14 calls | 2 req, 15 calls | 2 req, 14 calls |
| reset | 3 to 4 req, 9 to 11 calls | 2 req, one approval, 2 counted (see the earlier note) | 2 req, one approval |

Folded: the model called `weak_topics` in every script, first time, with the right threshold each
time (0.6, 0.8, 0.5), and in the reset task gathered it concurrently with `list_topics`; the
parked fan-out resumed through the outer approval as designed. Native: the model called
`weak_topics` from inside a script anyway (practice), paid one `unknown_function` retry (the copy
recovered it in one turn), and in the other two tasks did the fan-out itself and never called the
native tool. So the folded default is right and the README says so. The one extra call in the
folded column is `weak_topics` itself, counted through its metadata. Copy unchanged.

Trial transcripts: `.local/tutor-run-1.txt` (before) to `tutor-run-5.txt` (after),
`.local/tutor-compare-1.txt` and `-2.txt` (plain against script), `.local/tutor-dynamic-1.txt` and
`-2.txt` (flag on), `.local/tutor-suspend-1.txt` (approval), `.local/tutor-scripttool-1.txt` and
`-2.txt` (script tool folded, then native).

### 4. Keep CONTEXT.md current

Before any step 5 ADR, grep the diff for nouns not in the glossary. Either rename to a glossary
term or add the term with an "Avoid" line. Use `mattpocock-skills:domain-modeling`. Checked after
steps 2 and 3: the commits use only glossary terms (dispatch, fan-out, item, record, limits,
teaching copy); the example's own nouns (topic, mastery, exercise) are domain data, not engine
vocabulary. No change needed. Checked after item 1: added **Discovery** and **Announcement**; the diff's
"revealed" became "discovered" everywhere (`8afc7e1`). Item 3 added **Script tool** and **Input**
(`ef394a3`); the code says "script tool", never macro or saved plan. Item 4 added **Key**
(`879088f`); the store is named for its backend, and "durable" appears only in the ADR title.

### 5. Deferred backlog

In the order the design ranked them. Each is an ADR before code: `docs/adr/000N-<slug>.md`, front
matter `status: proposed`, one paragraph of decision and one of cost, in the voice of `0002`. Write
the ADR, run `mattpocock-skills:grilling` on it if the choice is not obvious, get the user's yes,
then `mattpocock-skills:tdd` for the code. One commit for the ADR, then commits per behaviour.

0. Bound through a derivation: done 2026-09-03 (`57517ff`).
1. `dynamic_catalog`: done 2026-09-03 (`f52fe14` to `e2d9840`), ADR 0003.
2. Suspend and detach: built 2026-09-03 (`3a0fc05` onward), ADR 0004. Trial and review outstanding;
   see "Next session".
3. Script tools: done 2026-09-04 (`ef394a3` to `abdd7fb`), ADR 0005.
4. Durable `RecordStore`: done 2026-09-04 (`879088f` to `692419b`), ADR 0006.
5. JS surface: a second front end compiling to the same `Plan`.
6. Upstreaming to `pydantic-ai-harness`: follow `agent_docs/capability-authoring.md` there.

## Reference repos (read-only siblings)

- `callscript/packages/callscript/src/` (`validate.ts`, `execute.ts`, `types.ts`) for behaviour to
  compare against.
- `pydantic-ai-harness/pydantic_ai_harness/code_mode/` for conventions; `AGENTS.md` and
  `agent_docs/capability-authoring.md` for the rules mirrored here.
- Installed `pydantic_ai` in `pydantic-ai-scriptmode/.venv` (2.37.0) for exact signatures.

## Verification commands

```bash
cd pydantic-ai-scriptmode
make all            # format, lint, typecheck, test
uv run pytest -q    # tests only
```

Note: `timeout` is not available on this macOS shell; use a Python subprocess with a timeout if a
test run needs bounding.

## Suggested skills

Call these with the Skill tool at the step named.

- `mattpocock-skills:writing-for-agents`: when editing the `run_script` description, the
  announcement sentence, or the teaching copy; all are agent-facing prose.
- `mattpocock-skills:domain-modeling`: step 4, and before any ADR in step 5. ADR 0006 added
  **Key**; ADR 0007 will need **Surface** or similar if a second language lands (today "surface"
  is used in ADR 0002 but not in the glossary).
- `mattpocock-skills:grilling`: on every ADR before the user's yes, as on 0004 to 0006. Two
  rounds worked for 0006: the frontier first, then what hung off the backend choice.
- `mattpocock-skills:tdd`: any engine behaviour change from step 3 or 5.
- `code-review` (or `mattpocock-skills:code-review`): before pushing a step 5 change. Run it at
  `medium`, not `high`: the `high` multi-agent run exhausted the session limit last time.
- `mattpocock-skills:handoff`: end of session. Its instruction is to write to a temp dir; the user
  has overridden that: update this file in place.
