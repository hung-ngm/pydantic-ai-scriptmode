---
status: accepted
---

# `dynamic_catalog` moves the catalog out of the tool description, mirroring harness `CodeMode`

The catalog is already rebuilt every step: `ScriptModeToolset.get_tools` recomputes the fold, so a
tool revealed mid-run by `ToolSearch` is callable from the next script. What is missing is cache
stability. The catalog is rendered into the `run_script` description, which providers key their
prompt cache on, so every discovery rewrites the description and busts the cache from that point.
`ScriptMode(dynamic_catalog=True)` mirrors harness `CodeMode` exactly: the description keeps only
the static prose and the limits paragraph; the catalog is stashed by `get_tools` and surfaced by
`get_instructions` as an `InstructionPart(dynamic=True)`, which Anthropic and Bedrock place after
the cache breakpoint; and a discovery is announced with an enqueued `SystemPromptPart` naming the
new tools, from `after_tool_execute` (local search) and `after_model_request` (native search). The
default stays `False`: with a fixed toolset the description is the shorter and cheaper place.

The cost is a second model-facing description variant that must be trialled on the tutor harness
like the first, one sentence of teaching copy pointing at the instructions instead of the
description, and per-run state (`_announced_tools`, `_last_catalog`) that has to be copied through
`for_run` and `for_run_step` so concurrent runs do not share it. None of the engine changes; the
plan, validator, and record are untouched.

## Considered options

- Do nothing and document that the fold is already dynamic: rejected, the cache cost is real for
  any agent that pairs `ScriptMode` with `ToolSearch`, and the flag name is what harness users
  will look for.
- Always put the catalog in instructions, no flag: rejected, it lengthens the system prompt for
  the common fixed-toolset case and diverges from `CodeMode`'s default.
- Stash the catalog on the `_RunScriptTool` instead of the toolset: rejected, `get_instructions`
  receives only the context, not the tools, so the toolset is the only place both hooks can reach.
