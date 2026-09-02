"""The `ScriptMode` capability."""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass, field

from pydantic_ai import AbstractToolset
from pydantic_ai.capabilities import AbstractCapability, CapabilityOrdering, ToolSearch
from pydantic_ai.tools import AgentDepsT, ToolSelector

from pydantic_ai_scriptmode._plan import Limits
from pydantic_ai_scriptmode._record import InMemoryRecordStore, RecordStore
from pydantic_ai_scriptmode._toolset import ScriptModeToolset


@dataclass
class ScriptMode(AbstractCapability[AgentDepsT]):
    """Fold selected tools into one `run_script` tool whose scripts compile to an inert plan.

    ```python
    from pydantic_ai import Agent
    from pydantic_ai_scriptmode import ScriptMode

    agent = Agent('anthropic:claude-sonnet-5', capabilities=[ScriptMode()])
    ```

    By default every eligible regular tool is folded. Pass a list of names or a predicate to
    `tools` to fold only some; the rest stay native tool calls.
    """

    tools: ToolSelector[AgentDepsT] = field(default='all')
    """Which tools to fold into `run_script`: `'all'`, a list of names, or `(ctx, tool_def) -> bool`."""

    max_retries: int = 3
    """Retries for `run_script` itself. Compile, validation, and uncaught runtime errors count."""

    _: KW_ONLY

    limits: Limits = field(default_factory=Limits)
    """Hard bounds on a plan. The live numbers are rendered into the `run_script` description."""

    record_store: RecordStore = field(default_factory=InMemoryRecordStore)
    """Where settled steps live between `run_script` calls, keyed by `conversation_id`."""

    def get_ordering(self) -> CapabilityOrdering:
        """Wrap around `ToolSearch` so `search_tools` stays native and discoveries can be folded."""
        return CapabilityOrdering(position='outermost', wraps=[ToolSearch])

    def get_wrapper_toolset(self, toolset: AbstractToolset[AgentDepsT]) -> AbstractToolset[AgentDepsT] | None:
        """Wrap the agent's assembled toolset in a `ScriptModeToolset`."""
        return ScriptModeToolset(
            wrapped=toolset,
            tool_selector=self.tools,
            max_retries=self.max_retries,
            limits=self.limits,
            record_store=self.record_store,
        )
