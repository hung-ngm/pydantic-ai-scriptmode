"""The `ScriptMode` capability."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError
from pydantic_ai import AbstractToolset, RunContext, ToolDefinition
from pydantic_ai.capabilities import AbstractCapability, CapabilityOrdering, ToolSearch
from pydantic_ai.messages import ModelResponse, NativeToolSearchReturnPart, SystemPromptPart, ToolCallPart
from pydantic_ai.tools import AgentDepsT, ToolSelector
from typing_extensions import TypedDict

from pydantic_ai_scriptmode._plan import Limits
from pydantic_ai_scriptmode._record import InMemoryRecordStore, RecordStore
from pydantic_ai_scriptmode._toolset import ScriptModeToolset

if TYPE_CHECKING:
    from pydantic_ai.capabilities.abstract import ValidatedToolArgs
    from pydantic_ai.models import ModelRequestContext

_ANNOUNCEMENT = (
    'New tools are now callable from `run_script`. Their signatures are in the catalog in the system instructions'
)


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

    dynamic_catalog: bool = False
    """Keep the `run_script` description cache-stable while the folded toolset grows.

    By default the folded tools' signatures are rendered into the `run_script` description, which
    providers key their prompt cache on; a tool revealed mid-run by `ToolSearch` rewrites it and
    busts the cache from that point. When `True` the description keeps only the static prose and
    the limits, the catalog moves into the system instructions as a dynamic `InstructionPart`
    (placed after the cache breakpoint by Anthropic and Bedrock), and each discovery is announced
    with a short `SystemPromptPart` so the model knows the new tools are callable. Pair it with
    `ToolSearch`; with a fixed toolset the default keeps the system prompt shorter.
    """

    _: KW_ONLY

    limits: Limits = field(default_factory=Limits)
    """Hard bounds on a plan. The live numbers are rendered into the `run_script` description."""

    record_store: RecordStore = field(default_factory=InMemoryRecordStore)
    """Where settled steps live between `run_script` calls, keyed by `conversation_id`."""

    _announced_tools: set[str] = field(default_factory=set[str], init=False, repr=False)

    async def for_run(self, ctx: RunContext[AgentDepsT]) -> ScriptMode[AgentDepsT]:
        """A fresh instance per run when announcing, so concurrent runs do not share what was announced."""
        if not self.dynamic_catalog:
            return self
        return replace(self)

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
            dynamic_catalog=self.dynamic_catalog,
        )

    async def after_tool_execute(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: Any,
    ) -> Any:
        """Announce the tools a local `search_tools` call revealed, when `dynamic_catalog` is on."""
        if self.dynamic_catalog and tool_def.tool_kind == 'tool-search':
            self._announce(ctx, _discovered_names(result))
        return result

    async def after_model_request(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        """Announce the tools a native (server-side) search revealed, when `dynamic_catalog` is on."""
        if self.dynamic_catalog:
            for part in response.parts:
                if isinstance(part, NativeToolSearchReturnPart):
                    self._announce(ctx, _discovered_names(part.content))
        return response

    def _announce(self, ctx: RunContext[AgentDepsT], names: Sequence[str]) -> None:
        """Enqueue one `SystemPromptPart` naming the tools not announced before in this run."""
        fresh = [n for n in names if n not in self._announced_tools]
        if not fresh:
            return
        self._announced_tools.update(fresh)
        listing = ', '.join(f'`{n}`' for n in fresh)
        # A mid-conversation `SystemPromptPart` renders inline on every provider, so it is cache-safe.
        ctx.enqueue(SystemPromptPart(content=f'{_ANNOUNCEMENT}: {listing}.'))


class _DiscoveredCatalog(TypedDict):
    """Lenient view of a tool-search return: the entry list, items left unvalidated."""

    discovered_tools: list[object]


class _DiscoveredEntry(TypedDict):
    """Lenient view of one discovered entry: only the name."""

    name: str


_CATALOG_ADAPTER = TypeAdapter(_DiscoveredCatalog)
_ENTRY_ADAPTER = TypeAdapter(_DiscoveredEntry)


def _discovered_names(content: object) -> list[str]:
    """Tool names in a search return, local or native. Malformed input yields fewer names, never an error."""
    try:
        catalog = _CATALOG_ADAPTER.validate_python(content)
    except ValidationError:
        return []
    names: list[str] = []
    for entry in catalog['discovered_tools']:
        try:
            names.append(_ENTRY_ADAPTER.validate_python(entry)['name'])
        except ValidationError:
            continue
    return names
