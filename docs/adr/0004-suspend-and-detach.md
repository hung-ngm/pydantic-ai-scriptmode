---
status: proposed
---

# A call that needs an approval parks the run; the approved re-run resumes from the record

Today a folded tool that raises `ApprovalRequired` with no `HandleDeferredToolCalls` to resolve it
inline ends the run with a `UserError`, because approving `run_script` on resume cannot reach the
nested call. This ADR gives the nested call a way to be reached: the record. When a call parks, the
step settles as `suspended` (a fan-out keeps every item's outcome, so a parked item does not undo
its done siblings), steps that do not depend on it keep running, and once nothing more can settle
the run's status is `suspended`, the record is saved, and `run_script` raises `ApprovalRequired`
whose metadata shows the approver the intent and every parked call with its tool, arguments, and
`_reason`. One approval resumes all of them: on the re-run Pydantic AI re-issues the same
`run_script` call with `ctx.tool_call_approved=True`, `call_tool` compiles the same script, and
`execute_plan(..., resolutions=...)` re-dispatches only the steps and items the record holds as
`suspended` under a matching hash, each with the resolution `approved` passed to `dispatch`, which
the adapter turns into `approved=True` on the nested `handle_call`. Everything else is reused from
the record as before. The resume reads nothing from `ctx.tool_call_metadata`: Pydantic AI echoes
metadata back only when the caller copies it into `DeferredToolResults`, so a resume that depended
on it would silently fail for anyone using `build_results(approve_all=True)`. `CallDeferred` stays a
`UserError`; the `resolutions` shape is callscript's and would carry an external result later, but
that is not decided here.

Denial happens above the toolset: Pydantic AI answers a denied `run_script` with a denial message
and never calls it, so the record stays `suspended` and the parked steps stay re-entry points. A
later script that asks again parks again, which is right, since the approver decides each time. A
step cannot loop forever: `Limits.max_suspend_attempts` (default 5, as callscript) counts on the
record per step name, and the count past the limit fails the step with an error the script's error
branch can catch. A suspension is not a model error: it does not touch `max_retries`, and the
execution retry message never fires for it. An error elsewhere in the same run wins over the
suspension, as in callscript (errors, then returns, then suspensions, in plan order), and the
parked steps stay `suspended` in the record for the corrected script to re-enter. Inline
resolution through `HandleDeferredToolCalls` remains the fast path: the nested `ToolManager`
consults it before the exception can escape, so a run parks only when nothing resolved the call.

The costs. `StepStatus`, `RunStatus`, and `ExecuteResult` grow a `suspended` variant, and
`StepRecord` grows per-item outcomes for fan-outs, which every `RecordStore` must carry. The public
`Dispatch` type gains a keyword `resolution` parameter, so an engine-direct `dispatch` that only
took `(step, args)` must add it; the README example changes. `Runner.schedule` must tell "pending
because a dependency is parked" from "pending because nothing is ready", which today is a
`PlanExecutionError`. A run with no `conversation_id` has no record to resume from, so a suspension
there is a `UserError` naming the cause. Partial approval is not offered: Pydantic AI has one
approval per `run_script` call, so the approver approves or denies the whole set the metadata
shows. And the description gets one sentence, that a call needing approval pauses the script and
the same script continues once approved, which has to be trialled on the tutor harness like the
rest of the copy.

## Considered options

- Keep the `UserError` and require `HandleDeferredToolCalls`: rejected, it makes human-in-the-loop
  approval, the ordinary case, unusable inside a script, while plain tools support it.
- Resume from `ctx.tool_call_metadata` (the parked step names and nested call ids in the
  `ApprovalRequired` metadata): rejected, the metadata is not echoed back unless the caller passes
  it into `DeferredToolResults.metadata`, so the resume would depend on a step most callers skip.
  The record already holds everything the resume needs and is keyed by the conversation.
- Halt the run at the first suspension, as an error does: rejected, independent steps would be
  re-dispatched on resume for no reason; letting them settle first matches callscript and leaves
  the approver waiting on nothing that was not theirs to decide.
- Re-dispatch a whole fan-out on resume instead of recording items: rejected, a side-effecting
  fan-out where one item parks (the tutor `reviews` shape) would repeat the done items' effects,
  which is the failure this feature exists to prevent.
- Approve every call in the resumed run, not only the parked ones: rejected, a tool that had not
  yet asked would run pre-approved, and `requires_approval=True` tools would never be asked at all.
- A `Suspend` payload persisted on the record, as callscript's `suspensions`: rejected for now, the
  adapter rebuilds what the approver sees from the plan and evaluated arguments, and the record
  must hold data only; the payload travels on `ExecuteResult` for the one call that raises.
