---
status: accepted
---

# A saved script becomes a script tool served by the same toolset, with its own record

A script that worked once is worth keeping: the developer saves its text under a name and the model
calls it like any tool, without authoring it again. `ScriptTool(name, script, description=...,
parameters=..., returns=...)` compiles the script at construction (a `CompileError` is the
developer's, raised at import), and `ScriptMode(scripts=[...])` hands the list to
`ScriptModeToolset`. The toolset serves script tools itself, not through a `FunctionToolset`:
Pydantic AI's `ToolManager` dispatches every call through the manager's own toolset, and the
agent-level manager knows only `run_script` and the native tools, so a script tool defined as an
ordinary function could never reach a folded tool when the model calls it directly. Instead
`get_tools` builds one `ToolsetTool` per script tool, whose `ToolDefinition` renders the declared
`parameters` (a Python type or a JSON schema) and `returns`, and `call_tool` runs the saved plan
the way it runs a model script: the same fold, the same `_Dispatcher`, a nested `ToolManager` built
over the toolset itself with the wrapped tools and the script tools in its `tools`, and
`execute_plan(..., input=<the validated arguments>)`. The call's return value is the plan's output,
whether the script reached its last line or a guard ended it. A script tool passes through the
`tools` selector like every other tool, so with the default `'all'` it is folded and appears in the
catalog next to the tools it composes, and one predicate makes it native. A saved script may call
every wrapped tool that is eligible for folding, whether or not the selector folded it, since the
selector is the model's view and the saved script is the developer's; the structural exclusions
(framework tools, unavailable and `unless_native` tools, other code-execution tools) still apply.
It may also call the script tools declared before it in the list, so composition is allowed and a
cycle is impossible by construction.

A script tool keeps its own record, keyed by conversation id, tool name, and a hash of its input,
not the conversation's record that `run_script` uses. Sharing would need callscript's explicit
merge: `Record.status`, `at`, `parked`, and `suspend_attempts` describe the last run, and a script
tool that ran inside a `run_script` would overwrite them mid-run, then be overwritten by the outer
`put`, which loaded its steps before the inner run began. The per-input key lets the reuse rule
treat `input` as data: the record keeps the `input` it was produced under, and a step that reads
it is reused or re-entered only under an equal one (without this an approved re-run could not find
the parked step, since every step of a saved script reads `input` somewhere). It lets a fan-out call
the same script tool with five inputs without the five records racing, and makes resume work:
Pydantic AI re-issues an approved call with the same arguments, so the same key is found. A
suspension inside a script tool takes the ADR 0004 path with no new plumbing. Called by the model,
the tool saves its record and raises `ApprovalRequired` with the same metadata shape as
`run_script`; the approved re-run has `ctx.tool_call_approved` and resumes from `record.parked`.
Called from a script, the nested `handle_call` lets that `ApprovalRequired` reach `_Dispatcher`,
which parks the outer step as it does for any tool; the outer approval re-dispatches it with
`approved=True`, the nested context carries the flag, and the inner run resumes from its own key.
A step that fails raises `ModelRetry` naming the step and its error: called by the model that is a
retry message the model answers by changing the arguments or giving up, within the script tool's
`max_retries`; called from a script it is a `CallError` the error branch can catch. A saved script
that names a tool the agent does not have is a `UserError` raised from `get_tools`, because the
script is the developer's and the fix is theirs; one that names a tool the agent has but that is
not available this step (undiscovered by `ToolSearch`, hidden by a `prepare` hook) hides the script
tool for the step with one warning, since availability is dynamic and an error there would take
the whole agent down on every run (found in review). The validator also checks every
`input.<field>` the script reads against the declared parameters, so a misspelt field fails at
construction. A script tool's record serves a retry or a resume only: a completed call is not
replayed from it, because the same arguments later in the conversation are a new call and the
model has no way to force a re-run as it has with a script (found in review).

The costs. `RecordStore` is keyed by a record key, not only a conversation id; the protocol's
parameter is renamed and the README example changes, though every existing store keeps working
since the key is still one string. `Record` grows an `input` field that every store must carry. The nested `ToolManager` for `run_script` is built over the
`ScriptModeToolset` instead of the wrapped toolset, so `call_tool` routes script tools to itself
and everything else onward; a test pins that a plain nested call still reaches the wrapped
toolset. A script tool's catalog is computed per tool (the eligible tools plus the earlier script tools),
so `get_tools` validates each saved plan every step; plans are small and the fold is already
rebuilt every step, so this is cheap, but it is work on the hot path. `ScriptTool` is a new public
class and `Plan` is not accepted as input: the text is what the message history holds and what the
developer copies out of a transcript, and a `Plan.from_dict` would be a second surface to keep in
step with the compiler. The description gets no new sentence: a script tool is a tool, and the
catalog already teaches how tools are called.

## Considered options

- A `FunctionToolset` of script tools contributed through `ScriptMode.get_toolset`, folded or kept
  native like any user tool: rejected, the function would dispatch through `ctx.tool_manager`, and
  when the model calls it directly that manager's `tools` are `run_script` and the natives; the
  folded tools are unreachable from there.
- Always native, as the backlog line said, regardless of the selector: rejected, a script tool the
  model can only call outside a script cannot be combined with other calls in one round trip, and
  the selector already expresses the choice per tool.
- Share the conversation record and merge the inner settlement into it, as callscript's
  `persist` does: rejected for now, the merge needs rules for `status`, `parked`, and the counts
  that the per-input key makes unnecessary; the cost is that a saved script never reuses a step
  the model's script already settled, which the hash rule would otherwise allow.
- A record per `tool_call_id`: rejected, the nested call ids restart at `__1` on a resumed run, so
  a script tool parked from inside a script would not find its record.
- Return `{'status': ..., 'output': ...}` as `run_script` does: rejected, the model reads a script
  tool as a tool with a return type, and the status is the tool's business; an error is an
  exception, a guard's value is a value.
- Let a guard inside a script tool end the hosting run, as callscript's `EarlyReturnSignal`
  composes: rejected, a Pydantic AI tool returns a value to its caller and nothing else; a script
  that wants to stop on the script tool's result writes its own guard.
- Raise for every saved script that cannot be validated this step, including over a tool that
  exists but is not available yet: the first cut did this; rejected in review, since a saved script
  over a `ToolSearch` tool would fail every run before the model could search. An unknown name
  still raises; only a known, unavailable tool hides.
- Accept a `Plan` (or `plan.to_dict()` from a return's metadata) as well as script text: rejected,
  see the costs.
