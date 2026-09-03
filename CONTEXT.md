# ScriptMode

A Pydantic AI capability where the model authors one script of tool calls that is compiled
into an inert plan and executed against the agent's tools, with no code ever running.
Exists so agents get Code Mode's one-round-trip batching without a sandbox.

## Language

**Script**:
The text the model authors in one `run_script` call. It is parsed and compiled, never executed.
_Avoid_: code, program, snippet

**Plan**:
The inert, serializable data a script compiles to. It is what gets validated, stored, and executed.
_Avoid_: script (when meaning the compiled form), workflow, DAG

**Step**:
One unit of a plan, identified by name, that other steps reference by that name.
_Avoid_: node, task, instruction

**Call**:
A step that invokes one folded tool with arguments.
_Avoid_: invocation, tool call (reserved for the agent-level concept)

**Derivation**:
A step that computes a value from earlier steps with a pure expression.
_Avoid_: let, assignment, transform

**Guard**:
A step that ends the run early with a value when its condition holds.
_Avoid_: early return, exit, break

**Fan-out**:
A call dispatched once per element of a list, bounded by a declared maximum.
_Avoid_: loop, batch, map step

**Expression**:
A pure, side-effect-free fragment of the authoring language used inside steps.
_Avoid_: formula, code

**Folded tool**:
An agent tool that has been hidden from the model and made callable from a script instead.
_Avoid_: sandboxed tool, mounted tool, wrapped tool

**Native tool**:
An agent tool the model still calls directly, outside any script.
_Avoid_: unfolded tool, raw tool

**Catalog**:
The rendered signatures of the folded tools that teach the model what a script may call.
_Avoid_: tool cards, tool list, manifest

**Discovery**:
A tool that `ToolSearch` makes available mid-run, so it is folded and enters the catalog from the next step.
_Avoid_: reveal, unlock, lazy tool

**Announcement**:
The one system message that names newly discovered tools so the model knows a script may call them.
_Avoid_: notification, hint, nudge

**Record**:
The serializable outcome of executing a plan: the settled value or error of each step.
_Avoid_: state, session, history

**Limits**:
The hard bounds a plan must satisfy before and during execution.
_Avoid_: budget, quota, config

**Intent**:
The one-line purpose the model states first in a script, kept on the plan for audit and approval.
_Avoid_: description, title, comment

**Error branch**:
The fallback expression a call settles to when it fails, written as `try`/`except` in a script.
_Avoid_: catch, handler, recovery

**Dispatch**:
The one function the engine is given to perform a call; the only way a plan reaches a tool.
_Avoid_: executor, handler, backend

**Teaching copy**:
The message for one rejection kind that tells the model the right spelling, not only what was wrong.
_Avoid_: error message, hint

**Suspension**:
A call parked on an approval it did not get, so the run stops there and the record keeps everything that settled.
_Avoid_: pause, deferral, interrupt

**Resolution**:
The answer that lets a parked call dispatch again: today only the approval.
_Avoid_: resume value, callback, response

**Script tool**:
A script the developer saved under a name and exposed as a tool; calling it runs its plan with the call's arguments bound as `input`.
_Avoid_: macro, saved plan, compiled tool, mounted tool, subroutine

**Input**:
The per-call data a plan reads as `input`: a script tool's arguments, nothing for `run_script`. A step that reads it is never reused.
_Avoid_: variables, arguments (those belong to a call), parameters (the declared schema)
