# Capability request for pydantic-ai-harness

Post this through the `Capability Request` issue template at
<https://github.com/pydantic/pydantic-ai-harness/issues/new/choose>; each heading below is one field
of that template. Fill the two placeholders before posting: the PyPI line (drop it if the package is
not released) and the transcript link if the repository is made public.

## Capability Name

ScriptMode

## Description

A second code mode that needs no sandbox. The model writes one short Python-subset script in a
single `run_script` call; the script is compiled into an inert plan of steps (calls, pure
derivations, guards, bounded fan-outs), validated whole against the folded tools' signatures and a
set of hard limits, and executed by a dataflow scheduler that can only invoke the agent's own
tools. Nothing the model writes runs as Python: expressions are evaluated by a tree walk over a
fixed set of `ast` nodes with a node budget, and the compiler rejects everything outside the
grammar with a message that names the spelling to use instead.

It solves the same problem as `CodeMode` (one model request per dependent stage of tool calls
instead of one per call) for hosts that cannot or do not want to run a sandbox: no Monty, no
subprocess, no dependency beyond `pydantic-ai-slim`. The design follows Vercel Labs' callscript
(<https://github.com/vercel-labs/callscript>), with a Python authoring surface so that the model is
taught the same `await tool(arg=value)` spelling `CodeMode` already teaches.

What is built and tested (package `pydantic-ai-scriptmode`, source
<https://github.com/hung-ngm/pydantic-ai-scriptmode>, `pip install pydantic-ai-scriptmode`):

- `ScriptMode(tools=..., limits=..., dynamic_catalog=..., record_store=..., scripts=...)`, a
  `WrapperToolset` capability with the same fold rules, `dynamic_catalog`, `ToolSearch`
  composition, and discovery announcement as `CodeMode`.
- A record per conversation: a failed script's corrected retry reuses the steps that settled; a
  call that raises `ApprovalRequired` parks the run and the approved re-run resumes from the record
  with only the parked calls re-dispatched. A `RecordStore` protocol with an in-memory default and
  a `SQLiteRecordStore` for resume across processes.
- Script tools: a developer-saved script served as a tool with its own parameter schema and its own
  record.
- Composition tests under `TemporalDurability` (engine workflow-side, folded calls as activities,
  clean replay, record reuse across a retry inside one workflow) and `DBOSDurability`.
- 235 tests, pyright strict, 100% of the grammar table exercised.

Trial against plain tools, same model (`anthropic:claude-opus-5`), same four tools, one run each,
not a benchmark:

| Task | Plain tools | ScriptMode |
| --- | --- | --- |
| practice | 4 requests, 12 calls, 1 retry, 7172 tokens | 3 requests, 12 calls, 1 retry, 8493 tokens |
| reviews | 4 requests, 14 calls, 6816 tokens | 2 requests, 14 calls, 4715 tokens |
| impossible | 3 requests, 9 calls, 4488 tokens | 2 requests, 9 calls, 4589 tokens |
| reset (approval) | 4 requests, 11 calls | 2 requests, one approval, only the two parked calls re-dispatched |

The model already parallelises calls it can see at once, so plain tools cost one request per
dependent stage; ScriptMode collapses every stage into two requests. Tokens are a wash at this
size (the tool description is about 1.5k tokens) and the saving grows with the number of stages.

## Use Case

An agent whose tools are HTTP or database calls and whose host is a plain web service, a Temporal
worker, or a DBOS workflow, where a sandboxed interpreter is either unavailable or a review burden
in itself. The operator wants the batching and the smaller history that `CodeMode` gives, plus a
plan they can read, hash, store, and approve before it runs: the intent line and every call with its
arguments are on the plan, which is what an approval sees. A second case is durable resume: a plan
that parks on an approval is resumed from its record in another process without re-running the
calls that already settled.

## Hooks / Integration Points

- `get_wrapper_toolset`: a `WrapperToolset` around the assembled toolset, serving `run_script` and
  the script tools, dispatching folded calls through a nested `ToolManager`
- `get_ordering`: `outermost`, wrapping `ToolSearch`, as `CodeMode` does
- `get_instructions`: the catalog as a dynamic `InstructionPart` when `dynamic_catalog=True`
- `after_tool_execute` and `before_model_request`: the discovery announcement
- `ApprovalRequired` from a folded tool parks the plan; `run_script` raises its own
  `ApprovalRequired` with the parked calls in `metadata`, and the approved re-run resumes
- `for_run`: a fresh instance per run when announcing, so concurrent runs do not share state

Proposed shape in the harness, if wanted: `pydantic_ai_harness/script_mode/` with the engine as
private modules next to `_capability.py` and `_toolset.py`, no new dependency and no extra, the
lazy root re-export, `README.md` plus `docs/script-mode.md` under Context management next to Code
Mode, and mirrored tests including the Temporal and DBOS ones. The standalone repository would be
archived after a merge. If the maintainers would rather it stayed a third-party package, that is a
fine answer too; the question is whether a sandbox-free code mode belongs in the harness at all.

## Prior Art / References

- Vercel Labs callscript: <https://github.com/vercel-labs/callscript> (the plan shape, the
  record, the durable runner)
- `pydantic_ai_harness.code_mode`: the conventions this mirrors
- Design records: <https://github.com/hung-ngm/pydantic-ai-scriptmode/tree/main/docs/adr>
  (0001 why an inert plan instead of a sandbox, 0002 why Python, 0004 suspend and resume,
  0006 the durable record)
