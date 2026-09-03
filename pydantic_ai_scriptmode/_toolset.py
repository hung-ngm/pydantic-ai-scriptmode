"""The toolset behind `ScriptMode`: folds selected tools into one `run_script` tool."""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError
from pydantic_ai import AbstractToolset, RunContext, ToolDefinition, WrapperToolset
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ModelRetry, UserError
from pydantic_ai.function_signature import FunctionSignature
from pydantic_ai.messages import InstructionPart, ToolCallPart, ToolReturn, ToolReturnPart
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.tools import AgentDepsT, ToolDenied, ToolSelector, matches_tool_selector
from pydantic_ai.toolsets.abstract import SchemaValidatorProt, ToolsetTool
from pydantic_core import to_jsonable_python
from typing_extensions import TypedDict

from pydantic_ai_scriptmode._compile import CompileError, compile_script
from pydantic_ai_scriptmode._execute import CallError, ExecuteResult, execute_plan
from pydantic_ai_scriptmode._plan import CallStep, Limits, Plan
from pydantic_ai_scriptmode._record import InMemoryRecordStore, RecordStore
from pydantic_ai_scriptmode._teaching import Issue
from pydantic_ai_scriptmode._validate import ToolSignature, validate_plan

RUN_SCRIPT_TOOL_NAME = 'run_script'


class _RunScriptArguments(TypedDict):
    script: Annotated[
        str, Field(description='The script to compile and execute. See the tool description for the grammar.')
    ]


_RUN_SCRIPT_ADAPTER = TypeAdapter(_RunScriptArguments)
_RUN_SCRIPT_JSON_SCHEMA = _RUN_SCRIPT_ADAPTER.json_schema()
_RUN_SCRIPT_ARGS_VALIDATOR: SchemaValidatorProt = _RUN_SCRIPT_ADAPTER.validator  # pyright: ignore[reportAssignmentType]

_INVALID_IDENT_CHARS = re.compile(r'[^a-zA-Z0-9_]')

_DESCRIPTION_HEAD = """\
Run a short script of tool calls in one round trip.

Write a Python-subset script. It is compiled to a plan of steps and executed against the tools in \
its catalog; it is never run as Python, so only the shapes in this table are accepted:

- a Python `#` comment stating the intent as the first line (never `//` or quotes; a docstring \
also works)
- `x = await tool(arg=value, ...)` calls a tool; arguments are keyword-only
- `x = <expression>` derives a value from earlier steps (pure: literals, f-strings, indexing, \
slicing, `.key` on dicts, comparisons, arithmetic, comprehensions, `len`/`sum`/`min`/`max`/`sorted`/\
`zip`/`enumerate`/`any`/`all`, `json.dumps`/`json.loads`, non-mutating `str`/`list`/`dict` methods)
- `if <condition>: return <value>` ends the run early with that value
- `x = [await tool(arg=i.field) for i in items[:N] if <filter>]` calls once per item, bounded by a \
literal slice `[:N]` or a literal list. Pick N as the most items you expect, not the limit: every \
fan-out's N counts toward the total-calls limit whether or not the items exist
- `a, b = await asyncio.gather(tool_a(...), tool_b(...))` runs calls concurrently; sequential \
`await`s run in order
- `try: x = await tool(...)` / `except Exception as e: x = <fallback>` handles a failed call; \
`_on_error='skip'` on a call settles it to `None` on failure instead (in a fan-out, only the failed items)
- `_reason='why'` on a call records why it is made
- `return <value>` as the last line is the result; without it the last step's value is returned

Not available: `while`, unbounded `for`, `def`, `class`, `import`, `print`, augmented assignment, \
nested awaits inside expressions, positional tool arguments.

Example, for tools `list_items() -> list[Item]` and `archive(item_id: str) -> str`:

```python
# Archive every stale item
items = await list_items()
stale = [i for i in items if i.stale]
if not stale:
    return {'archived': 0}
done = [await archive(item_id=i.id, _on_error='skip') for i in stale[:20]]
return {'archived': len([d for d in done if d])}
```

Independent steps run concurrently. Results settle per step and are kept for this conversation: if \
a script fails, a corrected script reuses the steps that already settled unchanged, so do not \
re-run work the error message lists as settled.\
"""


def _limits_paragraph(limits: Limits) -> str:
    return (
        f'Limits: at most {limits.max_steps} steps, {limits.max_items_per_fanout} items per fan-out, '
        f'{limits.max_total_calls} tool calls in total counting every fan-out at its bound N, '
        f'{limits.max_concurrency} calls in flight at once.'
    )


_FUNCTIONS_HEADER = (
    'The following tools are available inside a script. Call them with `await` and keyword '
    'arguments only; do not define or import anything.'
)

_CATALOG_IN_INSTRUCTIONS = (
    'The tools callable from a script are listed, with their signatures, in the system instructions; '
    'when nothing is listed there, no tool is callable yet.'
)

_SEARCH_ADDENDUM = (
    'Not every tool may be in the catalog at first. Use `search_tools` to discover more; a discovered '
    'tool is callable from the next `run_script`.'
)

_SEARCH_TOOLS_NAME = 'search_tools'


def sanitize_tool_name(name: str) -> str:
    safe = _INVALID_IDENT_CHARS.sub('_', name)
    if safe and safe[0].isdigit():
        safe = f'_{safe}'
    return safe or '_'


def _is_code_execution_tool(tool_def: ToolDefinition) -> bool:
    """A tool that executes its string argument (another `run_code`/`run_script`) stays a native peer."""
    return bool(tool_def.metadata and 'code_arg_name' in tool_def.metadata)


def _signature_of(tool_def: ToolDefinition) -> ToolSignature:
    schema = tool_def.parameters_json_schema
    properties = schema.get('properties', {})
    extra = schema.get('additionalProperties', False)
    return ToolSignature(
        name=tool_def.name,
        parameters=None if extra else frozenset(properties),
        required=frozenset(schema.get('required', ())),
    )


def _render_issues(headline: str, issues: Sequence[Issue]) -> str:
    return headline + '\n' + '\n'.join(f'- {i.render()}' for i in issues)


def _execution_retry(plan: Plan, outcome: ExecuteResult) -> str:
    """The retry message for a run that failed at a step, naming what a corrected script will reuse."""
    declared = {s.name for s in plan.steps}
    settled = sorted(n for n, s in outcome.record.steps.items() if s.status in ('done', 'skipped') and n in declared)
    message = f'Step `{outcome.at}` failed: {outcome.error}'
    if settled:
        message += f'\nSteps that settled and will be reused by a corrected script: {", ".join(settled)}.'
    return message


@dataclass
class _Dispatcher:
    """Performs one plan's calls through a nested `ToolManager`, keeping the parts for the metadata.

    Every failure the script can handle becomes a `CallError`. An unresolved approval or deferral
    is a `UserError`, as in harness `CodeMode`: the nested call is not a call the model made, so
    the agent cannot resume it by approving `run_script`. `HandleDeferredToolCalls` resolves it
    inline instead.
    """

    tool_manager: ToolManager[Any]
    sanitized_to_original: dict[str, str]
    parent_id: str
    calls: dict[str, ToolCallPart] = field(default_factory=dict[str, ToolCallPart])
    returns: dict[str, ToolReturnPart] = field(default_factory=dict[str, ToolReturnPart])

    async def __call__(self, step: CallStep, args: dict[str, Any]) -> Any:
        original = self.sanitized_to_original.get(step.tool, step.tool)
        call_id = f'{self.parent_id}__{len(self.calls) + 1}'
        part = ToolCallPart(tool_name=original, args=args, tool_call_id=call_id)
        self.calls[call_id] = part
        try:
            result = await self.tool_manager.handle_call(part, wrap_validation_errors=False)
        except (CallDeferred, ApprovalRequired) as e:
            raise UserError(
                f'Tool {original!r} raised {type(e).__name__} inside a script, but no `HandleDeferredToolCalls` '
                'capability resolved it. Add one to the agent so approval and deferral are handled inline; '
                'a script cannot pause and resume at one call.'
            ) from e
        except ModelRetry as e:
            raise CallError(e.message) from e
        except ValidationError as e:
            details = '; '.join(f'{".".join(str(p) for p in err["loc"])}: {err["msg"]}' for err in e.errors())
            raise CallError(f'invalid arguments for `{step.tool}`: {details}') from e
        except Exception as e:
            raise CallError(f'`{step.tool}` failed: {type(e).__name__}: {e}') from e
        if isinstance(result, ToolDenied):
            self.returns[call_id] = ToolReturnPart(
                tool_name=original, content=result.message, tool_call_id=call_id, outcome='denied'
            )
            raise CallError(f'`{step.tool}` was denied: {result.message}')
        metadata: Any = None
        if isinstance(result, ToolReturn):
            metadata = result.metadata
            result = result.return_value
        self.returns[call_id] = ToolReturnPart(
            tool_name=original, content=result, tool_call_id=call_id, metadata=metadata
        )
        return to_jsonable_python(result)


@dataclass(kw_only=True)
class _RunScriptTool(ToolsetTool[AgentDepsT]):
    """The `run_script` tool with the fold computed during `get_tools` cached on it."""

    callable_defs: dict[str, ToolDefinition]
    sanitized_to_original: dict[str, str]
    wrapped_tools: dict[str, ToolsetTool[AgentDepsT]]


@dataclass
class ScriptModeToolset(WrapperToolset[AgentDepsT]):
    """Implementation toolset for `ScriptMode`.

    Exposes one `run_script` tool next to any native tools. Tools matched by `tool_selector` are
    folded: their signatures are rendered into the `run_script` description and they become
    callable from a script. Framework control tools, hidden deferred tools, `unless_native`
    fallbacks, and other code-execution tools always stay native, as in harness `CodeMode`.
    """

    tool_selector: ToolSelector[AgentDepsT] = 'all'
    max_retries: int = 3
    limits: Limits = field(default_factory=Limits)
    record_store: RecordStore = field(default_factory=InMemoryRecordStore)
    dynamic_catalog: bool = False
    """Keep the catalog out of the `run_script` description and surface it through `get_instructions`."""

    _warned_no_return_schema: set[str] = field(default_factory=set[str], init=False, repr=False)
    # The catalog stashed by `get_tools` and read back by `get_instructions` in the same step.
    # Empty when `dynamic_catalog` is off or nothing is folded.
    _last_catalog: str = field(default='', init=False, repr=False)

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:
        """Return `run_script` plus the tools that stay native."""
        wrapped_tools = await self.wrapped.get_tools(ctx)
        folded: dict[str, ToolsetTool[AgentDepsT]] = {}
        native: dict[str, ToolsetTool[AgentDepsT]] = {}
        for name, tool in wrapped_tools.items():
            td = tool.tool_def
            if (
                td.tool_kind is not None
                or not ctx.is_tool_available(td)
                or td.unless_native
                or _is_code_execution_tool(td)
            ):
                native[name] = tool
            elif await matches_tool_selector(self.tool_selector, ctx, td):
                folded[name] = tool
            else:
                native[name] = tool

        if RUN_SCRIPT_TOOL_NAME in native:
            raise UserError(f"Tool name '{RUN_SCRIPT_TOOL_NAME}' is reserved for script mode. Rename your tool.")

        callable_defs, sanitized_to_original = self._fold(folded)
        if self.dynamic_catalog:
            description = self._static_description() + '\n\n' + _CATALOG_IN_INSTRUCTIONS
            self._last_catalog = _catalog(callable_defs)
        else:
            description = self._description(callable_defs)
            self._last_catalog = ''
        if _SEARCH_TOOLS_NAME in native:
            description += '\n\n' + _SEARCH_ADDENDUM
        result: dict[str, ToolsetTool[AgentDepsT]] = dict(native)
        result[RUN_SCRIPT_TOOL_NAME] = _RunScriptTool(
            toolset=self,
            tool_def=ToolDefinition(
                name=RUN_SCRIPT_TOOL_NAME,
                description=description,
                parameters_json_schema=_RUN_SCRIPT_JSON_SCHEMA,
                metadata={'code_arg_name': 'script', 'code_arg_language': 'python'},
                sequential=True,
            ),
            max_retries=self.max_retries,
            args_validator=_RUN_SCRIPT_ARGS_VALIDATOR,
            callable_defs=callable_defs,
            sanitized_to_original=sanitized_to_original,
            wrapped_tools=wrapped_tools,
        )
        return result

    async def for_run_step(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:
        """Rebuild around a changed wrapped toolset without losing the catalog stashed this step."""
        rebuilt = await super().for_run_step(ctx)
        if rebuilt is not self and isinstance(rebuilt, ScriptModeToolset):
            rebuilt._last_catalog = self._last_catalog
            rebuilt._warned_no_return_schema = self._warned_no_return_schema
        return rebuilt

    async def get_instructions(
        self, ctx: RunContext[AgentDepsT]
    ) -> str | InstructionPart | Sequence[str | InstructionPart] | None:
        """Append the catalog stashed by `get_tools` as a dynamic instruction, when there is one.

        `dynamic=True` puts it after the cache breakpoint on providers that split instructions
        (Anthropic, Bedrock), so a discovery changes the catalog without busting the static prefix.
        """
        # Through the base class, not `self.wrapped` directly: the base collects the wrapped
        # toolset's parts with their owner keys, so an upstream toolset's id stays on its own text.
        upstream = await super().get_instructions(ctx)
        if not self._last_catalog:
            return upstream
        catalog = InstructionPart(content=self._last_catalog, dynamic=True)
        if upstream is None:
            return catalog
        if isinstance(upstream, (str, InstructionPart)):
            return [upstream, catalog]
        return [*upstream, catalog]

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[AgentDepsT], tool: ToolsetTool[AgentDepsT]
    ) -> Any:
        """Compile, validate, and execute a script, or pass a native tool call through."""
        if not isinstance(tool, _RunScriptTool):
            return await self.wrapped.call_tool(name, tool_args, ctx, tool)

        parent_tm = ctx.tool_manager
        if parent_tm is None:
            raise UserError(
                'ScriptMode needs `ctx.tool_manager` to dispatch calls, and it is not set. Inside a Temporal '
                'workflow, run `run_script` as an activity or use ScriptMode outside the workflow.'
            )
        tool_manager = ToolManager(
            toolset=self.wrapped, root_capability=parent_tm.root_capability, ctx=ctx, tools=tool.wrapped_tools
        )

        try:
            plan = compile_script(tool_args['script'])
        except CompileError as e:
            raise ModelRetry(_render_issues('The script could not be compiled:', e.issues)) from e
        signatures = {name: _signature_of(td) for name, td in tool.callable_defs.items()}
        issues = validate_plan(plan, tools=signatures, limits=self.limits)
        if issues:
            raise ModelRetry(_render_issues('The script is not executable:', issues))

        dispatch = _Dispatcher(tool_manager, tool.sanitized_to_original, ctx.tool_call_id or 'pyd_ai_script_mode')
        conversation_id = ctx.conversation_id
        record = await self.record_store.get(conversation_id) if conversation_id is not None else None
        outcome = await execute_plan(plan, dispatch=dispatch, limits=self.limits, record=record)
        if conversation_id is not None:
            await self.record_store.put(conversation_id, outcome.record)

        if outcome.status == 'error':
            raise ModelRetry(_execution_retry(plan, outcome))
        metadata = {
            'script_mode': True,
            'plan': plan.to_dict(),
            'tool_calls': dispatch.calls,
            'tool_returns': dispatch.returns,
        }
        return ToolReturn(return_value={'status': outcome.status, 'output': outcome.output}, metadata=metadata)

    def _fold(self, tools: dict[str, ToolsetTool[AgentDepsT]]) -> tuple[dict[str, ToolDefinition], dict[str, str]]:
        callable_defs: dict[str, ToolDefinition] = {}
        sanitized_to_original: dict[str, str] = {}
        for name, tool in tools.items():
            td = tool.tool_def
            safe = sanitize_tool_name(name)
            if safe == RUN_SCRIPT_TOOL_NAME:
                raise UserError(f"Tool name '{name}' conflicts with the script mode tool. Rename your tool.")
            if safe in callable_defs:
                existing = sanitized_to_original.get(safe, safe)
                warnings.warn(
                    f'ScriptMode: tool {name!r} (sanitized to {safe!r}) collides with {existing!r} and is hidden.',
                    UserWarning,
                    stacklevel=2,
                )
                continue
            if not td.return_schema and name not in self._warned_no_return_schema:
                self._warned_no_return_schema.add(name)
                warnings.warn(
                    f'ScriptMode: tool {name!r} has no return schema; its signature will show `-> Any`.',
                    UserWarning,
                    stacklevel=2,
                )
            if safe != name:
                sanitized_to_original[safe] = name
                td = replace(td, name=safe)
            callable_defs[safe] = td
        return callable_defs, sanitized_to_original

    def _static_description(self) -> str:
        return '\n\n'.join([_DESCRIPTION_HEAD, _limits_paragraph(self.limits)])

    def _description(self, callable_defs: dict[str, ToolDefinition]) -> str:
        catalog = _catalog(callable_defs)
        if not catalog:
            return self._static_description()
        return self._static_description() + '\n\n' + catalog


def _catalog(callable_defs: dict[str, ToolDefinition]) -> str:
    """Render the folded tools' signatures, or `''` when nothing is folded."""
    if not callable_defs:
        return ''
    sigs = [td.function_signature for td in callable_defs.values()]
    conflicting = FunctionSignature.get_conflicting_type_names(sigs)
    sections = [_FUNCTIONS_HEADER]
    type_blocks = FunctionSignature.render_type_definitions(sigs, conflicting)
    if type_blocks:
        sections.append('```python\n' + '\n\n'.join(type_blocks) + '\n```')
    function_blocks = [
        td.render_signature('...', is_async=True, conflicting_type_names=conflicting) for td in callable_defs.values()
    ]
    sections.append('```python\n' + '\n\n'.join(function_blocks) + '\n```')
    return '\n\n'.join(sections)
