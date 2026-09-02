# Handoff: pydantic-ai-scriptmode (complete and green; next is first commit, review, real-model trial)

Date: 2026-09-02
Workspace: `/Users/hungng/Documents/AI/experiments/pydantic-experiments/`
Project: `pydantic-ai-scriptmode/`
This file is the single source of truth for progress. Update it in place at the end of each
session; do not write handoff copies elsewhere (no temp-directory copies, no progress in memory).

## Where things stand

The package is complete. `make all` (ruff format, ruff check, pyright strict, pytest) is green:
136 passed, no xfails, no skips. Nothing is committed: the project is not yet a git repository.

Session history, newest first:

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

`.local/` is git-ignored scratch: the scheduler answer key and a swap helper from the learning
phase. Both are redundant now. Safe to delete; the trial script in step 3 below can live there too.

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
  so the script's error branch can catch them. `ApprovalRequired` / `CallDeferred` propagate.
- Untyped tools have `return_schema == {}` (not `None`) in pydantic-ai 2.37, so the "no return
  schema" warning checks falsiness.
- The record is saved even when the run fails, so a retry reuses settled steps. The retry message
  names them.
- `Runner.schedule` is event-driven: in-flight steps are tasks keyed by name, `asyncio.wait`
  with `FIRST_COMPLETED` wakes on any settlement and launches what became ready. A halt gates new
  launches only, so in-flight steps settle and the record holds what their tools did. When
  `run_step` raises (approval, deferral, bug) a `finally` cancels and awaits the remaining tasks so
  none outlives the run. Open question for review: whether that cancel is right once
  `HandleDeferredToolCalls` resumes a plan from its record.
- `unknown_function` is raised from two places with different details: the expression parser
  passes `name` only, the validator passes `name` and `step`. Its template uses only `name`. The
  parametrized test in `tests/test_teaching.py` catches templates that name an undocumented
  detail, but not one that a second raise site omits; check both sites when adding a kind.
- `tests/test_script_mode.py::test_validation_error_is_a_retry` asserts on rendered copy, not kind
  names. Kind names no longer appear in any model-facing text.

## Next steps, in order

Each step says what to do, what "done" looks like, and what to write back here.

### 1. Make it a repository and commit

```bash
cd pydantic-ai-scriptmode
make all                      # must be green before the first commit
git init -b main
git add -A
git status                    # confirm .venv/, .local/, __pycache__/ are absent
git commit -m "ScriptMode: inert-plan script mode for Pydantic AI"
```

Done when `git log` shows one commit and `git status` is clean. Do not add a remote; the user
decides where it lives. Record the commit hash under "Where things stand".

### 2. Whole-package code review

Run `code-review` on the working tree (or `mattpocock-skills:code-review`). There is no diff to
review, so point it at the package: `pydantic_ai_scriptmode/` and `tests/`. Order the findings by
these candidates first, then whatever else it raises:

1. `_toolset.py` `call_tool`: length and whether the three retry messages should be one helper.
2. `_expr.py` `_call_builtin`: whether every builtin charges the `NodeBudget` consistently
   (`sorted`, `zip`, `enumerate` build lists; `range` is bounded by what?).
3. `_execute.py` `Runner.schedule`: the cancel-on-escape decision above. Read how
   `pydantic_ai_harness/code_mode/` and `HandleDeferredToolCalls` resume after `ApprovalRequired`
   before deciding. If cancelling loses work the resume would have reused, drop the `finally`.
4. `_compile.py` `is_tool_call`: the forgot-`await` heuristic misfires on a call to a name defined
   later in the script. Decide if that matters; it only changes which rejection kind fires.

Fix what is clear, one commit per fix, each followed by `make all`. Anything you decide not to fix
goes in a "Known and accepted" list under this section. Done when the review has no open findings.

### 3. First real-model trial

Purpose: tune the `run_script` description in `_toolset.py` and the teaching copy in
`_teaching.py` from what a model actually gets wrong. The test suite uses only `TestModel` and
`FunctionModel`; keep it that way. The trial is a scratch script, not a test.

Setup:

- Write `.local/trial.py` (git-ignored). Build an `Agent` with `ScriptMode` over three or four
  small tools that make the shapes interesting: one that returns a list, one that takes an item
  from that list, one that can fail, one untyped. The README "Usage" example is a fine start.
- Provider and model come from the environment. Do not write a key into any file in the workspace;
  use the provider's usual env var and note in this file which provider was used, not the key.
- Give it a handful of tasks that need a fan-out, a guard, an error branch, and one that is
  impossible with the folded tools (to see how it handles `unknown_tool`).

Capture, for each task: the first script the model wrote, every retry message it received, how
many turns to success. Put the raw transcript in `.local/`, and the findings here:

- Which rejection kinds fired, in order of frequency.
- For each, whether the copy got the model to the right spelling on the next turn. Rewrite the
  ones that did not. A template change needs no test change unless a test asserts on its text.
- What the description failed to teach up front. Change the description and the README together;
  the README is the reference when they disagree.

Done when the model succeeds in one turn on the ordinary tasks and recovers in one retry on the
rest. Commit as "Tune run_script description and teaching copy from first trial".

### 4. Keep CONTEXT.md current

After steps 2 and 3, grep the diff for nouns not in the glossary. Either rename to a glossary term
or add the term with an "Avoid" line. Use `mattpocock-skills:domain-modeling`. This session
introduced no new vocabulary.

### 5. Deferred backlog

In the order the design ranked them. Each is an ADR before code.

1. `dynamic_catalog`: rebuild the catalog per run so tools added mid-conversation are foldable.
2. Suspend and detach: let a plan pause at an approval and resume from its record without
   re-dispatching settled steps (this is where the schedule cancel question is finally decided).
3. Script-as-tool: expose a saved plan as a native tool.
4. Durable `RecordStore`: file or SQLite; the protocol already supports it (README example).
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

- `code-review` (or `mattpocock-skills:code-review`): step 2, before any fix commits.
- `mattpocock-skills:writing-for-agents`: step 3, when editing the `run_script` description or
  the teaching copy; both are agent-facing prose.
- `mattpocock-skills:domain-modeling`: step 4, and before any ADR in step 5.
- `mattpocock-skills:tdd`: any engine behaviour change from step 2 or 5.
- `mattpocock-skills:grilling`: only if a design fork appears that the two ADRs do not cover.
- `mattpocock-skills:handoff` is not registered in this session's skill list even though it is
  installed under `~/.claude/plugins/cache/claude-plugins-official/mattpocock-skills/`; its
  instruction is to write the doc to a temp dir, which the user has overridden: update this file.
