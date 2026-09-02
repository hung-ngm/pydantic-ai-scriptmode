# Handoff: pydantic-ai-scriptmode (backlog started; ADR 0003 awaits the user's yes)

Date: 2026-09-03
Workspace: `/Users/hungng/Documents/AI/experiments/pydantic-experiments/`
Project: `pydantic-ai-scriptmode/`
This file is the single source of truth for progress. Update it in place at the end of each
session; do not write handoff copies elsewhere (no temp-directory copies, no progress in memory).

## Where things stand

The package is complete, reviewed, trialled against a real model, committed, and pushed. `make all`
(ruff format, ruff check, pyright strict, pytest) is green: 150 passed, no xfails, no skips.
`git log` on `main`, newest first (handoff-only commits omitted):

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
`logfire>=4.41.0` added to the `examples` group in `pyproject.toml` and `uv.lock`.

Steps 1 to 4 are done. Backlog item 0 is done. Item 1 has its ADR (`docs/adr/0003-dynamic-catalog.md`,
`status: proposed`) and is waiting for the user's yes before code.

Session history, newest first:

- 2026-09-03 (latest): backlog item 0 done by TDD (`57517ff`): the compiler keeps `bounds`, the
  literal bound of every derivation, and a fan-out over a bare name inherits it; a rebinding drops
  it. Tests include the exact script from `.local/tutor-compare-2.txt`. README grammar paragraph
  updated; teaching copy unchanged, so no tutor run was needed. Wrote ADR 0003 for item 1 after
  reading harness `CodeMode.dynamic_catalog`; see "Next session".
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

`examples/tutor.py` is a test harness first and an example second; the user intends to remove it
later, so nothing else may depend on it. It builds the same four tools into two agents, one with
plain tools and one with `ScriptMode`, runs each task on both, prints every script, retry, and
return, and ends with a comparison table (model requests, tool calls, total tokens).
`uv run python examples/tutor.py [task ...]`, tasks `practice`, `reviews`, `impossible`. Needs
`ANTHROPIC_API_KEY` in `.env` (git-ignored). All dependency groups are default in `[tool.uv]`, so
plain `uv sync` and `uv run` install the linters and the Anthropic extra together.

How a task runs in script mode: the model gets one tool, `run_script`, whose description carries
the four signatures. It answers with one script. `ScriptModeToolset.call_tool` compiles it to a
plan, validates it against the signatures and `Limits`, and `execute_plan` drives the steps
through `_Dispatcher`, which calls each folded tool through a nested `ToolManager`. The model's
second request sees `{'status': ..., 'output': ...}` and writes the summary. A retry message
(compile, validate, or a failed step) costs one more request and settled steps are reused.

`.local/` is git-ignored scratch: `tutor-run-1.txt` to `tutor-run-5.txt` are the trial transcripts;
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

1. `cd pydantic-ai-scriptmode && git pull && uv sync --all-groups && make all`. Expect 150 passed.
2. Get the user's yes (or changes) on `docs/adr/0003-dynamic-catalog.md`, then flip it to
   `status: accepted` and build it with `mattpocock-skills:tdd`, mirroring
   `pydantic-ai-harness/pydantic_ai_harness/code_mode/` (`_capability.py` lines 105 to 215,
   `_toolset.py` lines 555 to 700, tests at `tests/code_mode/test_code_mode.py` line 2917 on).
   Pieces: `dynamic_catalog` field on `ScriptMode` and `ScriptModeToolset`; `_last_catalog` stash
   in `get_tools` and `get_instructions` returning an `InstructionPart(dynamic=True)`; `for_run` /
   `for_run_step` copying the stash; `_announced_tools` on the capability with `for_run` returning
   a copy; `after_tool_execute` and `after_model_request` enqueueing a `SystemPromptPart`. Then a
   tutor run with the flag on. If the user says no, move to item 2.
3. Any change to the description, the teaching copy, or `Limits` must be checked with
   `uv run python examples/tutor.py` (needs `ANTHROPIC_API_KEY` in `.env`): all three tasks
   should succeed in one turn with zero retries, as they do now. Compare against
   `.local/tutor-run-5.txt`.
4. Push after every commit. Update this file at the end of the session (not a temp copy).

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

Trial transcripts: `.local/tutor-run-1.txt` (before) to `tutor-run-5.txt` (after),
`.local/tutor-compare-1.txt` and `-2.txt` (plain against script).

### 4. Keep CONTEXT.md current

Before any step 5 ADR, grep the diff for nouns not in the glossary. Either rename to a glossary
term or add the term with an "Avoid" line. Use `mattpocock-skills:domain-modeling`. Checked after
steps 2 and 3: the commits use only glossary terms (dispatch, fan-out, item, record, limits,
teaching copy); the example's own nouns (topic, mastery, exercise) are domain data, not engine
vocabulary. No change needed.

### 5. Deferred backlog

In the order the design ranked them. Each is an ADR before code: `docs/adr/000N-<slug>.md`, front
matter `status: proposed`, one paragraph of decision and one of cost, in the voice of `0002`. Write
the ADR, run `mattpocock-skills:grilling` on it if the choice is not obvious, get the user's yes,
then `mattpocock-skills:tdd` for the code. One commit for the ADR, then commits per behaviour.

0. Bound through a derivation: done 2026-09-03 (`57517ff`).
1. `dynamic_catalog`: ADR 0003 proposed 2026-09-03. The fold was already dynamic; the item is
   cache placement of the catalog, mirroring harness `CodeMode` (instructions part plus
   discovery announcement). See "Next session" for the build plan.
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
