---
status: accepted
---

# Compile scripts to an inert plan instead of executing them in a sandbox

Pydantic AI Harness already ships `CodeMode`, which runs model-authored Python in a Monty sandbox.
ScriptMode takes callscript's alternative: the script is parsed into a plan of steps and pure
expressions, validated whole, and executed by a scheduler that can only invoke folded tools.
Nothing the model writes runs as Python. We accept a smaller language (no general computation,
no unbounded loops) in exchange for no sandbox dependency, static validation that reports every
issue before anything runs, hard call bounds by construction, a serializable record that can be
resumed with settled steps reused, and dataflow parallelism without the model spelling it.

## Considered options

- Wrap or extend harness `CodeMode`: rejected, the sandbox is the thing being removed.
- Evaluate expressions with `eval` on a restricted namespace: rejected, restricted `eval` is not a
  security boundary and would make the plan non-inert.
