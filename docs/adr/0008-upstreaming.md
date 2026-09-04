---
status: accepted
---

# Upstreaming goes issue first, then a vendored port into the harness

The capability was built to be upstreamable to `pydantic-ai-harness`, and its conventions already
mirror harness `CodeMode` (`dynamic_catalog`, the announcement, `for_run` isolation, the nested
`ToolManager`). The harness is pydantic's own repository with its own process: every PR links an
issue (`.github/PULL_REQUEST_TEMPLATE.md`; a `capability-request` issue template exists), a change
to `pyproject.toml` or `uv.lock` needs a maintainer's `dependencies:approved` label, a capability
that overrides `for_run` must ship public `Agent`-path tests under `TemporalDurability` and DBOS
(`agent_docs/review-checklist.md`, "Tests"), and product fit ("a clear user or dogfooding need") is
the first review question. So the order is: an issue, posted by the user under their own account
from a draft in `docs/upstream/issue.md`, with the trial table and a `pip install` line; no port
until a maintainer answers it. When the answer is yes, the port is vendored: the engine modules
(`_teaching`, `_expr`, `_plan`, `_compile`, `_validate`, `_record`, `_stores`, `_script_tool`,
`_execute`) move under `pydantic_ai_harness/script_mode/` as private modules next to
`_capability.py` and `_toolset.py`, with no dependency change and no extra, since the engine imports
only `pydantic_core` and one name from `pydantic_ai.tools`. The harness public surface is what a
harness user needs: `ScriptMode`, `ScriptTool`, `RecordStore`, `InMemoryRecordStore`,
`SQLiteRecordStore`, `Limits`, re-exported lazily from the root package as the authoring guide
requires; `compile_script`, `execute_plan`, and the plan types stay private there. The name stays
`ScriptMode`, a noun for a subsystem the model uses, next to `CodeMode`; the docs page is
`docs/script-mode.md` under "Context management", where Code Mode lives, with the partner
navigation PR in pydantic-ai that the docs conventions require. The durability tests are written
now, in this repository, mirroring `tests/code_mode/test_temporal.py` and `test_dbos.py`, with
`temporalio` and `dbos` in a `durability` dependency group and the Temporal dev server the SDK
downloads, so the issue can say the capability passes the one gate that can be passed before
asking, and so the question a reviewer will ask first, whether the record should ride on
Temporal's history instead of a `RecordStore`, is answered by us with a test rather than by them
with a comment. The package is released to PyPI as `pydantic-ai-scriptmode` 0.1.0 by the user, so
the issue has an installable reference and a dependency-based port stays possible if a maintainer
prefers it. After a merge this repository is archived with a README pointer to the harness
capability; the PyPI release stays as it is.

The costs. The port waits on a reply that may be no, in which case the package stays third-party
(pydantic-ai's extensibility guide covers publishing capabilities as packages) and the durability
tests and PyPI release are still worth having. Vendoring means two copies exist between the PR and
the archive; the archive is what stops them drifting, and it is why the standalone repository does
not become the engine's long-term home. The durability tests add two heavy test dependencies and
a dev-server download to this repository's `durability` group only; `make all` does not run them
by default, a separate `make durability` does. The harness's 100% branch-coverage gate and
`tests/test_docs_parity.py` will find gaps this repository's suite does not enforce; they are
the PR's work, not this ADR's.

## Considered options

- A cold PR without an issue: rejected. The template requires the issue, and a 3k-line capability
  from outside with no prior contact is the shape most likely to be closed unread.
- Stay third-party and only propose: the fallback if the answer is no, not the plan. The user's
  goal for the package is the harness.
- An extra depending on `pydantic-ai-scriptmode` from PyPI, the engine staying here as
  `pydantic-monty` does for `CodeMode`: rejected. Monty is pydantic's own package; a dependency on
  an individual's package needs `dependencies:approved` and a maintainer's trust in a release
  cadence, and the engine has nothing to gain from a second home.
- Keep this repository as the engine's home after a merge and sync the harness copy by hand:
  rejected, two copies drift and only the harness's gates are enforced.
- A mechanism name (`PlanMode`, `InertCodeMode`): rejected. `ScriptMode` names what the model
  uses, as `CodeMode` does; the mechanism belongs in the docs page, not the class name.
- Leave the durability tests for the PR branch: rejected, see the decision.
- Post the issue and the PR from the agent through `gh`: rejected. The contact is under the user's
  name; the agent drafts, the user posts.
