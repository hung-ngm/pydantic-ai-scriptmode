# Handoff: pydantic-ai-scriptmode (committed and reviewed; next is the real-model trial)

Date: 2026-09-03
Workspace: `/Users/hungng/Documents/AI/experiments/pydantic-experiments/`
Project: `pydantic-ai-scriptmode/`
This file is the single source of truth for progress. Update it in place at the end of each
session; do not write handoff copies elsewhere (no temp-directory copies, no progress in memory).

## Where things stand

The package is complete, reviewed, committed, and pushed. `make all` (ruff format, ruff check,
pyright strict, pytest) is green: 145 passed, no xfails, no skips. `git log` on `main`, newest
first (handoff-only commits omitted):

- `84047d8` Validator refuses a hand-built fan-out with no bound
- `69963e5` Unresolved approval inside a script is a UserError; dispatch is a class
- `d52d178` Fan-out waits for every item; skip is per item; no function-valued steps
- `9a95a74` Charge sequence growth, catch OverflowError, refuse str.format
- `79005aa` ScriptMode: inert-plan script mode for Pydantic AI

Remote: `origin` is the private repo `https://github.com/hung-ngm/pydantic-ai-scriptmode`;
`main` tracks `origin/main` and is in sync. Working tree clean. Commit straight to `main` and push
after each commit; no force-push, no other branches yet.

The one open item is step 3, the real-model trial, blocked only on a provider key: none of the
usual `*_API_KEY` variables was set in the last session's environment.

Session history, newest first:

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
- `CONTEXT.md`: glossary (16 terms). Use these words in code, docs, tests, and this file.
- `docs/adr/0001-*.md`, `0002-*.md`: why inert plan, why Python surface.
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
| `_record.py` | `Record`, `StepRecord`, `RecordStore` protocol, `InMemoryRecordStore`, `reusable_steps` | `tests/test_execute.py::TestRecordReuse` |
| `_execute.py` | `Runner` (with `schedule`), `execute_plan`, `CallError`, `Dispatch` | `tests/test_execute.py` |
| `_toolset.py` | `ScriptModeToolset(WrapperToolset)`, `run_script` description and dispatch | `tests/test_script_mode.py` |
| `_capability.py` | `ScriptMode(AbstractCapability)` | `tests/test_script_mode.py` |

Public surface is `pydantic_ai_scriptmode/__init__.py` (`__all__`).

`.local/` is git-ignored scratch: `trial.py` for step 3, plus the scheduler answer key and a swap
helper from the learning phase, both redundant now and safe to delete.

## Decisions made while coding (not in the ADRs or README)

- Reuse rule is stricter than callscript: a settled step is reused only if name and hash match AND
  every step it references was also reused, and never if it reads `input`. Docstring on
  `reusable_steps` explains why.
- Sequential `await`s get `after` edges on call steps; derivations get none; a guard is a fence
  handled by `Runner.ready_steps`, not by edges.
- "Forgot `await`" is a compile-time heuristic: a bare call to a name that is neither a builtin nor a
  step defined earlier. Truly unknown functions are the validator's `unknown_function`.
- Fan-out bound must be a literal: `xs[:N]`, `xs[a:N]`, or a list display. Anything else is
  `unbounded_for`.
- `try`/`except` accepts exactly one call statement and one recovery statement (`x = <expr>` to the
  same name, or `pass`). The error is bound to the `as` name as its message string.
- Anonymous steps are named `_callN` / `_guardN` by position.
- Tool exceptions, `ModelRetry`, argument `ValidationError`, and `ToolDenied` all become `CallError`
  so the script's error branch can catch them. `ApprovalRequired` / `CallDeferred` are handled
  inline or become `UserError`; see the `_Dispatcher` entry below.
- Untyped tools have `return_schema == {}` (not `None`) in pydantic-ai 2.37, so the "no return
  schema" warning checks falsiness.
- The record is saved even when the run fails, so a retry reuses settled steps. The retry message
  names them.
- `Runner.schedule` is event-driven: in-flight steps are tasks keyed by name, `asyncio.wait`
  with `FIRST_COMPLETED` wakes on any settlement and launches what became ready. A halt gates new
  launches only, so in-flight steps settle and the record holds what their tools did. When
  `run_step` raises a `finally` cancels and awaits the remaining tasks so none outlives the run.
  Settled in review: only a `UserError` (unresolved approval) or a bug can raise there, so the
  cancel is right. Nothing resumes a plan from its record today; that is backlog item 2.
- A fan-out gathers with `return_exceptions=True` so every item settles before the step does
  (`Runner.collect_items`). `_on_error='skip'` on a fan-out settles only the failed items to
  `None`; the step is `done` with a list. A whole-step skip (`skipped`, value `None`) is for a
  single call only. `try`/`except` does not accept a fan-out body.
- `ApprovalRequired` / `CallDeferred` from a folded tool are resolved inline by
  `HandleDeferredToolCalls` through the nested `ToolManager`. Without a handler they become a
  `UserError` (`_Dispatcher`), as in harness `CodeMode`: approving `run_script` on resume rebuilds
  the nested call with `tool_call_approved=False`, so it would raise again forever (proved
  empirically before the change).
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

## Review findings (step 2, done 2026-09-03)

Fixed, one commit each, listed under "Where things stand". The four candidates the previous
session named resolved as: (1) `call_tool` split into `_Dispatcher` and `_execution_retry`; the
compile and validate retries share `_render_issues`, the execution retry is a different shape and
stays separate. (2) `_call_builtin` charges consistently; the real bypass was `*` and `+` on
sequences, now charged. (3) Cancel is right; see "Decisions". (4) Accepted, below.

Known and accepted:

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

1. `cd pydantic-ai-scriptmode && git pull && make all`. Expect 145 passed.
2. Check for a key: `env | grep -c API_KEY`. If zero, ask the user which provider to use and to
   export the key in the shell (`! export ...` in the prompt), then continue with step 3. If the
   user has no key to hand, skip to step 5 and come back.
3. Do step 3 below end to end, including the doc write-back, before touching anything else. It is
   the only source of evidence about what the model actually gets wrong; every later change to the
   description or teaching copy should cite it.
4. Push after every commit. Update this file at the end of the session (not a temp copy).

## Next steps, in order

Each step says what to do, what "done" looks like, and what to write back here.

### 3. First real-model trial

Purpose: tune the `run_script` description in `_toolset.py` and the teaching copy in
`_teaching.py` from what a model actually gets wrong. The test suite uses only `TestModel` and
`FunctionModel`; keep it that way. The trial is a scratch script, not a test.

Setup, already written: `.local/trial.py` (git-ignored) builds an `Agent` with `ScriptMode` over
four tools (`list_issues` returns a list, `close_issue` takes an item, `lookup_assignee` fails half
the time, `repo_summary` is untyped) and runs four tasks: fan-out, guard, error branch, and one
impossible with the folded tools (`unknown_tool`). It writes `.local/trial-transcript.md` with
every script, every retry message, and a count of retry headlines by frequency.

```bash
SCRIPTMODE_TRIAL_MODEL=<provider:model> uv run python .local/trial.py
```

The provider's usual env var must hold the key. Do not write a key into any file in the
workspace; note here which provider and model were used, not the key.

Plan for the session:

1. Run the trial once as is. If the model is `pydantic_ai.models.ALLOW_MODEL_REQUESTS`-blocked,
   that is `tests/conftest.py` leaking; the trial does not import it, so it should not happen.
2. Read `.local/trial-transcript.md` top to bottom before changing anything. Classify every retry
   by rejection kind (the headline of each retry names it in prose; map back to `RejectionKind`
   in `_teaching.py`).
3. For each kind that fired: did the next script fix that line? If yes, the copy works, leave it.
   If no, rewrite that one template under `mattpocock-skills:writing-for-agents`, then rerun only
   that task (edit `TASKS` in `trial.py` to one entry). A template change needs no test change
   unless a test asserts on its text; `grep -n` the tests for a phrase before changing it.
4. Anything the model got wrong on its *first* script is a description gap, not a copy gap. Fix
   `_DESCRIPTION_HEAD` in `_toolset.py` and the README grammar table together; the README is the
   reference when they disagree. Rerun all four tasks after a description change.
5. Watch specifically for: (a) `reuse after success` giving a stale answer when a task repeats a
   step name across runs (the four tasks share one agent, so the record is shared; if the guard
   task reuses `issues` from the fan-out task, that is the stale read the "Known and accepted"
   entry warned about, and the fix is to reuse only from an `error` record); (b) the model writing
   `for` without a slice, and whether `unbounded_for` copy gets it to `[:N]` in one turn; (c) the
   impossible task: it should stop after one `unknown_tool` retry, not keep trying.
6. Record here: provider and model used; kinds by frequency; which templates changed and why;
   which description lines changed and why; turns-to-success per task before and after.

Done when the model succeeds in one turn on the ordinary tasks and recovers in one retry on the
rest. Commit as "Tune run_script description and teaching copy from first trial", then push.

### 4. Keep CONTEXT.md current

After step 3, grep the diff for nouns not in the glossary. Either rename to a glossary term or add
the term with an "Avoid" line. Use `mattpocock-skills:domain-modeling`. Checked after step 2:
the review commits use only glossary terms (dispatch, fan-out, item, record); no change needed.

### 5. Deferred backlog

In the order the design ranked them. Each is an ADR before code: `docs/adr/000N-<slug>.md`, front
matter `status: proposed`, one paragraph of decision and one of cost, in the voice of `0002`. Write
the ADR, run `mattpocock-skills:grilling` on it if the choice is not obvious, get the user's yes,
then `mattpocock-skills:tdd` for the code. One commit for the ADR, then commits per behaviour.

1. `dynamic_catalog`: rebuild the catalog per run so tools added mid-conversation are foldable.
   Smallest item; a good first ADR. Today `get_tools` already recomputes the fold each call, so
   the question is only whether the description must be stable within a run for prompt caching
   (harness `CodeMode` has a `dynamic_catalog` flag for exactly this; read it first).
2. Suspend and detach: let a plan pause at an approval and resume from its record without
   re-dispatching settled steps. Needs: the record saved before the `UserError`, a `suspended`
   run status (callscript has one, `execute.ts` line ~71), and a way for `run_script` to be
   re-entered with the approval bound to the nested call id. This replaces the `UserError` path
   in `_Dispatcher`.
3. Script-as-tool: expose a saved plan as a native tool.
4. Durable `RecordStore`: file or SQLite; the protocol already supports it (README example).
   Now cheap to do safely because records can no longer hold closures.
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

- `mattpocock-skills:writing-for-agents`: step 3, when editing the `run_script` description or
  the teaching copy; both are agent-facing prose.
- `mattpocock-skills:domain-modeling`: step 4, and before any ADR in step 5.
- `mattpocock-skills:grilling`: on a step 5 ADR whose choice is not obvious, before the user's yes.
- `mattpocock-skills:tdd`: any engine behaviour change from step 3 or 5.
- `code-review` (or `mattpocock-skills:code-review`): before pushing a step 5 change. Run it at
  `medium`, not `high`: the `high` multi-agent run exhausted the session limit last time.
- `mattpocock-skills:handoff`: end of session. Its instruction is to write to a temp dir; the user
  has overridden that: update this file in place.
