"""End-to-end tests through `Agent(capabilities=[ScriptMode()])` with a `FunctionModel` that emits scripts."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import AbstractToolset, Agent, DeferredToolRequests, DeferredToolResults, RunContext, ToolDefinition
from pydantic_ai.capabilities import HandleDeferredToolCalls, ToolSearch
from pydantic_ai.exceptions import ApprovalRequired, UnexpectedModelBehavior, UserError
from pydantic_ai.messages import (
    InstructionPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    NativeToolSearchReturnPart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.usage import RunUsage
from typing_extensions import TypedDict

from pydantic_ai_scriptmode import (
    RUN_SCRIPT_TOOL_NAME,
    InMemoryRecordStore,
    Limits,
    ScriptMode,
    ScriptModeToolset,
    ScriptTool,
)

pytestmark = pytest.mark.anyio

ISSUES = [{'number': 1, 'stale': True}, {'number': 2, 'stale': False}, {'number': 3, 'stale': True}]


def build_agent(*scripts: str, extra: list[Any] | None = None, **kwargs: Any) -> tuple[Agent[None, str], list[str]]:
    """An agent whose model replies to each request with the next script, then with the tool result as text."""
    closed: list[str] = []
    remaining = list(scripts)

    async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if remaining:
            return ModelResponse(parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': remaining.pop(0)})])
        last = messages[-1].parts[-1]
        assert isinstance(last, ToolReturnPart)
        return ModelResponse(parts=[TextPart(str(last.content))])

    agent = Agent(FunctionModel(model), deps_type=type(None), capabilities=[*(extra or []), ScriptMode[None](**kwargs)])

    @agent.tool_plain
    async def list_issues(repo: str) -> list[dict[str, Any]]:
        """List issues in a repository."""
        return ISSUES

    @agent.tool_plain
    async def close_issue(repo: str, number: int) -> str:
        """Close one issue."""
        closed.append(f'{repo}#{number}')
        return f'closed {number}'

    return agent, closed


def build_approval_agent(
    *scripts: str, parks_on: int | None = None, extra: list[Any] | None = None
) -> tuple[Agent[None, str | DeferredToolRequests], list[Any]]:
    """An agent with one tool, `danger`, that needs approval; `seen` logs each call's approval flag.

    With `parks_on` only that `n` needs approval and `seen` logs `(n, approved)`.
    """
    seen: list[Any] = []
    remaining = list(scripts)

    async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if remaining:
            return ModelResponse(parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': remaining.pop(0)})])
        last = messages[-1].parts[-1]
        assert isinstance(last, ToolReturnPart)
        return ModelResponse(parts=[TextPart(str(last.content))])

    agent = Agent(
        FunctionModel(model),
        deps_type=type(None),
        output_type=[str, DeferredToolRequests],
        capabilities=[*(extra or []), ScriptMode[None]()],
    )

    @agent.tool
    async def danger(ctx: RunContext[None], n: int) -> int:
        """Needs approval."""
        if parks_on is None:
            seen.append(ctx.tool_call_approved)
        else:
            seen.append((n, ctx.tool_call_approved))
        if not ctx.tool_call_approved and (parks_on is None or n == parks_on):
            raise ApprovalRequired(metadata=None if parks_on is None else {'n': n})
        return n

    return agent, seen


def retry_text(messages: list[ModelMessage]) -> str:
    """The retry prompt the model received after its first script."""
    part = messages[2].parts[0]
    assert isinstance(part, RetryPromptPart)
    return part.model_response()


async def describe(agent: Agent[None, str], **kwargs: Any) -> TestModel:
    """Run once with a model that calls nothing, so the tool definitions it was shown can be read."""
    model = TestModel(call_tools=[])
    await agent.run('go', model=model, **kwargs)
    return model


SCRIPT = """
# Close stale issues
issues = await list_issues(repo='api')
stale = [i for i in issues if i.stale]
if not stale:
    return {'closed': 0}
closed = [await close_issue(repo='api', number=i.number) for i in stale[:20]]
return {'closed': len(closed)}
"""


class TestScriptMode:
    async def test_runs_a_script_end_to_end(self):
        agent, closed = build_agent(SCRIPT)
        result = await agent.run('go')
        assert result.output == "{'status': 'done', 'output': {'closed': 2}}"
        assert closed == ['api#1', 'api#3']
        # The model saw exactly one tool.
        request = result.all_messages()[0]
        assert [p.part_kind for p in request.parts] == ['user-prompt']

    async def test_only_run_script_is_visible(self):
        agent, _ = build_agent()
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        names = [t.name for t in model.last_model_request_parameters.function_tools]
        assert names == [RUN_SCRIPT_TOOL_NAME]
        description = model.last_model_request_parameters.function_tools[0].description or ''
        assert 'async def list_issues(*, repo: str)' in description
        assert 'async def close_issue(*, repo: str, number: int)' in description
        assert 'at most 20 steps' in description

    async def test_limits_are_rendered(self):
        agent, _ = build_agent(limits=Limits(max_steps=7))
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        assert 'at most 7 steps' in (model.last_model_request_parameters.function_tools[0].description or '')

    async def test_selector_keeps_other_tools_native(self):
        agent, _ = build_agent(tools=['close_issue'])
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        names = sorted(t.name for t in model.last_model_request_parameters.function_tools)
        assert names == ['list_issues', RUN_SCRIPT_TOOL_NAME]

    async def test_compile_error_is_a_retry_with_every_issue(self):
        agent, _ = build_agent('while True:\n    pass\nimport os', SCRIPT)
        result = await agent.run('go')
        text = retry_text(result.all_messages())
        assert 'could not be compiled' in text and 'line 1' in text and 'line 3' in text
        assert result.output == "{'status': 'done', 'output': {'closed': 2}}"

    async def test_validation_error_is_a_retry(self):
        agent, _ = build_agent("x = await nope(a=1)\ny = await close_issue(repo='r')", SCRIPT)
        result = await agent.run('go')
        text = retry_text(result.all_messages())
        assert 'not executable' in text
        assert '`nope` in step `x` is not a folded tool' in text
        assert '`close_issue` requires `number`' in text

    async def test_runtime_error_retry_names_settled_steps_and_retry_reuses_them(self):
        agent, closed = build_agent(
            "issues = await list_issues(repo='api')\nn = issues[0].nope\nx = await close_issue(repo='api', number=n)",
            "issues = await list_issues(repo='api')\nn = issues[0].number\nx = await close_issue(repo='api', number=n)",
        )
        result = await agent.run('go')
        text = retry_text(result.all_messages())
        assert 'Step `n` failed' in text and 'settled' in text and 'issues' in text
        assert closed == ['api#1']
        assert result.output == "{'status': 'done', 'output': 'closed 1'}"

    async def test_retries_are_bounded(self):
        agent, _ = build_agent(*['while True:\n    pass'] * 5, max_retries=1)
        with pytest.raises(UnexpectedModelBehavior):
            await agent.run('go')

    async def test_tool_error_can_be_caught_by_the_script(self):
        agent, _ = build_agent(
            "try:\n    x = await close_issue(repo='api', number='not-a-number')\nexcept Exception as e:\n    x = e\nreturn x"
        )
        result = await agent.run('go')
        assert 'invalid arguments' in result.output and 'number' in result.output

    async def test_denied_call_is_a_call_error(self):
        agent, _ = build_agent("x = await close_issue(repo='api', number=1, _on_error='skip')\nreturn x")
        result = await agent.run('go')
        assert result.output == "{'status': 'done', 'output': 'closed 1'}"

    async def test_inline_resolution_is_the_fast_path_and_without_an_output_type_the_framework_says_so(self):
        def build(*capabilities: Any) -> tuple[Agent[None, str], list[bool]]:
            seen: list[bool] = []

            async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                last = messages[-1].parts[-1]
                if isinstance(last, ToolReturnPart):
                    return ModelResponse(parts=[TextPart(str(last.content))])
                return ModelResponse(parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': 'x = await danger(n=1)'})])

            agent = Agent(FunctionModel(model), deps_type=type(None), capabilities=[*capabilities, ScriptMode[None]()])

            @agent.tool
            async def danger(ctx: RunContext[None], n: int) -> int:
                seen.append(ctx.tool_call_approved)
                if not ctx.tool_call_approved:
                    raise ApprovalRequired
                return n

            return agent, seen

        # Nothing resolved the approval inline, so `run_script` parks and asks for it (ADR 0004); this
        # agent cannot receive the request, and Pydantic AI's error names both ways to fix that.
        agent, seen = build()
        with pytest.raises(UserError, match='DeferredToolRequests.*HandleDeferredToolCalls'):
            await agent.run('go')
        assert seen == [False]

        agent, seen = build(HandleDeferredToolCalls(lambda ctx, requests: requests.build_results(approve_all=True)))
        result = await agent.run('go')
        assert result.output == "{'status': 'done', 'output': 1}"
        assert seen == [False, True]

    async def test_a_parked_call_suspends_run_script_and_the_approved_re_run_resumes_it(self):
        agent, seen = build_approval_agent("x = await danger(n=1, _reason='needed')\nreturn x")
        first = await agent.run('go')
        requests = first.output
        assert isinstance(requests, DeferredToolRequests) and len(requests.approvals) == 1
        call = requests.approvals[0]
        assert call.tool_name == RUN_SCRIPT_TOOL_NAME
        assert requests.metadata[call.tool_call_id] == {
            'script_mode': True,
            'intent': None,
            'suspended': [
                {'step': 'x', 'item': None, 'tool': 'danger', 'args': {'n': 1}, 'reason': 'needed', 'metadata': None}
            ],
        }
        assert seen == [False]

        resumed = await agent.run(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={call.tool_call_id: True}),
        )
        assert resumed.output == "{'status': 'done', 'output': 1}"
        assert seen == [False, True]

    async def test_a_denied_run_script_leaves_the_parked_step_to_be_asked_again(self):
        agent, seen = build_approval_agent('x = await danger(n=1)\nreturn x', 'x = await danger(n=1)\nreturn x')
        first = await agent.run('go')
        assert isinstance(first.output, DeferredToolRequests)
        call_id = first.output.approvals[0].tool_call_id
        denied = await agent.run(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={call_id: False}),
        )
        # The model saw the denial and wrote the same script again: it parks again, unresolved.
        assert isinstance(denied.output, DeferredToolRequests)
        assert seen == [False, False]

    async def test_a_fan_out_with_a_parked_item_resumes_only_that_item(self):
        agent, seen = build_approval_agent('ys = [await danger(n=i) for i in [1, 2, 3]]\nreturn ys', parks_on=2)
        first = await agent.run('go')
        assert isinstance(first.output, DeferredToolRequests)
        call = first.output.approvals[0]
        assert first.output.metadata[call.tool_call_id]['suspended'] == [
            {'step': 'ys', 'item': 1, 'tool': 'danger', 'args': {'n': 2}, 'reason': None, 'metadata': {'n': 2}}
        ]
        resumed = await agent.run(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={call.tool_call_id: True}),
        )
        assert resumed.output == "{'status': 'done', 'output': [1, 2, 3]}"
        assert seen == [(1, False), (2, False), (3, False), (2, True)]

    async def test_an_approval_covers_only_the_calls_it_was_asked_for(self):
        """A parked step from a denied script must not run approved on a later script's approval."""
        seen: list[tuple[str, bool]] = []
        scripts = [
            'y = await mild(n=1)\nx = await danger(n=1)\nreturn x',
            'y = await needs(n=1)\nx = await danger(n=1)\nreturn x',
        ]

        async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if scripts:
                return ModelResponse(parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': scripts.pop(0)})])
            last = messages[-1].parts[-1]
            assert isinstance(last, ToolReturnPart)
            return ModelResponse(parts=[TextPart(str(last.content))])

        agent = Agent(
            FunctionModel(model),
            deps_type=type(None),
            output_type=[str, DeferredToolRequests],
            capabilities=[ScriptMode[None]()],
        )

        def gated(name: str) -> None:
            async def tool(ctx: RunContext[None], n: int) -> int:
                seen.append((name, ctx.tool_call_approved))
                if not ctx.tool_call_approved:
                    raise ApprovalRequired
                return n

            tool.__name__ = name
            agent.tool(tool)

        @agent.tool_plain
        async def mild(n: int) -> int:
            return n

        gated('needs')
        gated('danger')

        first = await agent.run('go')
        assert isinstance(first.output, DeferredToolRequests)
        denied = await agent.run(
            message_history=first.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={first.output.approvals[0].tool_call_id: False}),
        )
        assert isinstance(denied.output, DeferredToolRequests)
        call = denied.output.approvals[0]
        assert [e['tool'] for e in denied.output.metadata[call.tool_call_id]['suspended']] == ['needs']
        approved = await agent.run(
            message_history=denied.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={call.tool_call_id: True}),
        )
        # `needs` ran approved; `danger`, parked by the denied script, was asked again, not run.
        assert isinstance(approved.output, DeferredToolRequests)
        assert seen == [('danger', False), ('needs', False), ('needs', True), ('danger', False)]

    async def test_an_approved_re_run_with_no_record_is_a_user_error(self):
        agent, _ = build_approval_agent('x = await danger(n=1)\nreturn x')
        first = await agent.run('go')
        assert isinstance(first.output, DeferredToolRequests)
        call_id = first.output.approvals[0].tool_call_id
        fresh, _ = build_approval_agent()  # a different store: the record is gone
        with pytest.raises(UserError, match='no record'):
            await fresh.run(
                message_history=first.all_messages(),
                deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
            )

    async def test_function_in_result_is_a_retry(self):
        agent, _ = build_agent("issues = await list_issues(repo='api')\nreturn [len]", 'x = 1')
        result = await agent.run('go')
        assert 'Step `return` failed: the result holds a function' in retry_text(result.all_messages())

    async def test_record_is_shared_across_runs_in_a_conversation(self):
        store = InMemoryRecordStore()
        agent, _ = build_agent("issues = await list_issues(repo='api')\nreturn len(issues)", record_store=store)
        first = await agent.run('go')
        conversation_id = first.all_messages()[-1].conversation_id
        assert conversation_id is not None
        record = await store.get(conversation_id)
        assert record is not None and record.steps['issues'].status == 'done'

    async def test_tool_search_stays_native_and_deferred_tools_are_not_folded(self):
        agent, _ = build_agent(extra=[ToolSearch()])

        @agent.tool_plain(defer_loading=True)
        def later(x: int) -> int:
            """Only reachable through search."""
            return x

        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        tools = {t.name: t for t in model.last_model_request_parameters.function_tools}
        assert sorted(tools) == ['later', RUN_SCRIPT_TOOL_NAME, 'search_tools']
        # `later` stays native with its deferred-loading flag intact instead of being folded.
        assert tools['later'].defer_loading is True
        assert 'def later' not in (tools[RUN_SCRIPT_TOOL_NAME].description or '')

    async def test_reserved_tool_name(self):
        agent = Agent(TestModel(), deps_type=type(None), capabilities=[ScriptMode[None](tools=[])])

        @agent.tool_plain
        def run_script(script: str) -> str:
            return script

        with pytest.raises(UserError, match='reserved'):
            await agent.run('go')

    async def test_sanitized_tool_names(self):
        async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(
                    parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': 'x = await get_thing(k=1)\nreturn x'})]
                )
            last = messages[-1].parts[-1]
            assert isinstance(last, ToolReturnPart)
            return ModelResponse(parts=[TextPart(str(last.content))])

        def get_thing(k: Any) -> Any:
            return k * 2

        toolset: FunctionToolset[None] = FunctionToolset()
        toolset.add_function(get_thing, name='get-thing')
        agent = Agent(FunctionModel(model), deps_type=type(None), toolsets=[toolset], capabilities=[ScriptMode[None]()])
        with pytest.warns(UserWarning, match='no return schema'):
            result = await agent.run('go')
        assert result.output == "{'status': 'done', 'output': 2}"

    async def test_metadata_carries_plan_and_nested_calls(self):
        agent, _ = build_agent(SCRIPT)
        result = await agent.run('go')
        part = result.all_messages()[2].parts[0]
        assert isinstance(part, ToolReturnPart)
        assert part.metadata['script_mode'] is True
        assert [c.tool_name for c in part.metadata['tool_calls'].values()] == [
            'list_issues',
            'close_issue',
            'close_issue',
        ]
        assert part.metadata['plan']['intent'] == 'Close stale issues'


class TestToolsetDirect:
    async def test_tool_manager_required(self):
        toolset = ScriptModeToolset(wrapped=FunctionToolset())
        ctx: RunContext[None] = RunContext(deps=None, model=TestModel(), usage=RunUsage())
        tools = await toolset.get_tools(ctx)
        with pytest.raises(UserError, match='tool_manager'):
            await toolset.call_tool(RUN_SCRIPT_TOOL_NAME, {'script': 'x = 1'}, ctx, tools[RUN_SCRIPT_TOOL_NAME])


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def run_context() -> RunContext[None]:
    """A bare context with a pending-message queue, so capability hooks can enqueue."""
    return RunContext(deps=None, model=TestModel(), usage=RunUsage(), pending_messages=[])


class TestDynamicCatalog:
    """`ScriptMode(dynamic_catalog=True)`: catalog in instructions, discoveries announced.

    Two surfaces: `ScriptModeToolset` moves the signatures out of the `run_script` description and
    into a dynamic `InstructionPart`; `ScriptMode` announces newly discovered tools with an enqueued
    `SystemPromptPart`.
    """

    async def test_description_drops_signatures_keeps_head_and_limits(self):
        toolset = ScriptModeToolset(wrapped=FunctionToolset([add]), dynamic_catalog=True)
        tools = await toolset.get_tools(run_context())
        description = tools[RUN_SCRIPT_TOOL_NAME].tool_def.description or ''
        assert 'async def add' not in description
        assert 'Run a short script of tool calls' in description
        assert 'at most 20 steps' in description
        assert 'system instructions' in description

    async def test_default_keeps_catalog_in_description(self):
        toolset = ScriptModeToolset(wrapped=FunctionToolset([add]))
        tools = await toolset.get_tools(run_context())
        assert 'async def add(*, a: int, b: int) -> int' in (tools[RUN_SCRIPT_TOOL_NAME].tool_def.description or '')
        assert toolset._last_catalog == ''  # pyright: ignore[reportPrivateUsage]

    async def test_stash_is_empty_when_nothing_is_folded(self):
        toolset = ScriptModeToolset(wrapped=FunctionToolset(), dynamic_catalog=True)
        tools = await toolset.get_tools(run_context())
        assert 'system instructions' in (tools[RUN_SCRIPT_TOOL_NAME].tool_def.description or '')
        assert toolset._last_catalog == ''  # pyright: ignore[reportPrivateUsage]

    async def test_catalog_is_a_dynamic_instruction_part(self):
        toolset = ScriptModeToolset(wrapped=FunctionToolset([add]), dynamic_catalog=True)
        ctx = run_context()
        await toolset.get_tools(ctx)
        instructions = await toolset.get_instructions(ctx)
        assert isinstance(instructions, InstructionPart)
        assert 'async def add(*, a: int, b: int) -> int' in instructions.content
        assert instructions.dynamic is True

    @pytest.mark.parametrize(
        ('upstream', 'expected_prefix'),
        [
            ('wrapped', ['wrapped']),
            (InstructionPart(content='part'), ['part']),
            (['a', InstructionPart(content='b')], ['a', 'b']),
        ],
    )
    async def test_catalog_is_appended_to_upstream_instructions(self, upstream: Any, expected_prefix: list[str]):
        class Upstream(FunctionToolset[None]):
            async def get_instructions(self, ctx: RunContext[None]) -> Any:
                return upstream

        toolset = ScriptModeToolset(wrapped=Upstream([add]), dynamic_catalog=True)
        ctx = run_context()
        await toolset.get_tools(ctx)
        instructions = await toolset.get_instructions(ctx)
        assert isinstance(instructions, list)
        # Upstream text arrives normalized to `InstructionPart`s; the catalog is appended last.
        assert [p.content for p in instructions[:-1] if isinstance(p, InstructionPart)] == expected_prefix
        assert isinstance(instructions[-1], InstructionPart) and 'async def add' in instructions[-1].content

    async def test_no_instructions_when_off_or_empty(self):
        for toolset in (
            ScriptModeToolset(wrapped=FunctionToolset([add])),
            ScriptModeToolset(wrapped=FunctionToolset(), dynamic_catalog=True),
        ):
            ctx = run_context()
            await toolset.get_tools(ctx)
            assert await toolset.get_instructions(ctx) is None

    async def test_step_rebuild_keeps_the_stash(self):
        class Changing(FunctionToolset[None]):
            async def for_run_step(self, ctx: RunContext[None]) -> AbstractToolset[None]:
                return Changing(list(self.tools.values()))

        toolset = ScriptModeToolset(wrapped=Changing([add]), dynamic_catalog=True)
        ctx = run_context()
        await toolset.get_tools(ctx)
        stashed = toolset._last_catalog  # pyright: ignore[reportPrivateUsage]
        assert stashed
        rebuilt = await toolset.for_run_step(ctx)
        assert isinstance(rebuilt, ScriptModeToolset) and rebuilt is not toolset
        assert rebuilt._last_catalog == stashed  # pyright: ignore[reportPrivateUsage]

    async def test_catalog_reaches_the_model_through_agent(self):
        agent, _ = build_agent(dynamic_catalog=True)
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        assert 'async def list_issues' not in (model.last_model_request_parameters.function_tools[0].description or '')
        result = await agent.run('go', model=model)
        request = result.all_messages()[0]
        assert isinstance(request, ModelRequest)
        assert 'async def list_issues(*, repo: str)' in (request.instructions or '')

    async def test_for_run_isolates_announcements_when_on_and_is_identity_when_off(self):
        on = ScriptMode[None](dynamic_catalog=True)
        on._announced_tools.add('weather')  # pyright: ignore[reportPrivateUsage]
        fresh = await on.for_run(run_context())
        assert fresh is not on and isinstance(fresh, ScriptMode)
        assert fresh._announced_tools == set()  # pyright: ignore[reportPrivateUsage]
        off = ScriptMode[None]()
        assert await off.for_run(run_context()) is off


ANNOUNCED = (
    'New tools are now callable from `run_script`. Their signatures are in the catalog in the system instructions'
)


def search_tool_def() -> ToolDefinition:
    return ToolDefinition(name='search_tools', description='', parameters_json_schema={}, tool_kind='tool-search')


async def announce_local(
    cap: ScriptMode[None], ctx: RunContext[None], result: Any, tool_def: ToolDefinition | None = None
):
    await cap.after_tool_execute(
        ctx,
        call=ToolCallPart(tool_name='search_tools', args={}, tool_call_id='c1'),
        tool_def=tool_def or search_tool_def(),
        args={},
        result=result,
    )


def announcements(ctx: RunContext[None]) -> list[str]:
    """The text of every `SystemPromptPart` the capability enqueued."""
    out: list[str] = []
    for pending in ctx.pending_messages or []:
        for message in pending.messages:
            assert isinstance(message, ModelRequest)
            for part in message.parts:
                assert isinstance(part, SystemPromptPart)
                out.append(part.content)
    return out


class TestDiscoveryAnnouncement:
    async def test_local_search_return_is_announced_once(self):
        cap = ScriptMode[None](dynamic_catalog=True)
        ctx = run_context()
        await announce_local(cap, ctx, {'discovered_tools': [{'name': 'weather'}, {'name': 'news'}]})
        await announce_local(cap, ctx, {'discovered_tools': [{'name': 'weather'}]})
        assert announcements(ctx) == [f'{ANNOUNCED}: `weather`, `news`.']

    async def test_native_search_return_is_announced(self):
        cap = ScriptMode[None](dynamic_catalog=True)
        ctx = run_context()
        response = ModelResponse(
            parts=[
                TextPart('hi'),
                NativeToolSearchReturnPart(
                    tool_name='tool_search', content={'discovered_tools': [{'name': 'weather'}]}, tool_call_id='c1'
                ),
            ]
        )
        await cap.after_model_request(ctx, request_context=None, response=response)  # pyright: ignore[reportArgumentType]
        assert announcements(ctx) == [f'{ANNOUNCED}: `weather`.']

    async def test_inert_when_off_or_not_a_search_tool(self):
        ctx = run_context()
        await announce_local(ScriptMode[None](), ctx, {'discovered_tools': [{'name': 'weather'}]})
        plain = ToolDefinition(name='add', description='', parameters_json_schema={})
        await announce_local(ScriptMode[None](dynamic_catalog=True), ctx, {'discovered_tools': [{'name': 'x'}]}, plain)
        assert announcements(ctx) == []

    @pytest.mark.parametrize(
        'result',
        [
            'not a dict',
            {},
            {'discovered_tools': 'not a list'},
            {'discovered_tools': []},
            {'discovered_tools': ['s', {'name': 1}]},
        ],
    )
    async def test_malformed_or_empty_return_is_not_announced(self, result: Any):
        ctx = run_context()
        await announce_local(ScriptMode[None](dynamic_catalog=True), ctx, result)
        assert announcements(ctx) == []

    async def test_search_then_script_calls_the_discovered_tool(self):
        """End to end: the model searches, is told the tool is callable, and calls it from a script."""
        descriptions: list[str] = []
        prompts: list[str] = []

        async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            descriptions.append(
                next(t.description or '' for t in info.function_tools if t.name == RUN_SCRIPT_TOOL_NAME)
            )
            last = messages[-1]
            assert isinstance(last, ModelRequest)
            prompts.append(
                '\n'.join(str(p.content) for p in last.parts if isinstance(p, (SystemPromptPart, UserPromptPart)))
            )
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart('search_tools', {'queries': ['weather']}, tool_call_id='s1')])
            if len(messages) == 3:
                assert 'async def weather(*, city: str) -> str' in (last.instructions or '')
                return ModelResponse(
                    parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': "w = await weather(city='Oslo')\nreturn w"})]
                )
            part = last.parts[-1]
            assert isinstance(part, ToolReturnPart)
            return ModelResponse(parts=[TextPart(str(part.content))])

        agent = Agent(
            FunctionModel(model),
            deps_type=type(None),
            capabilities=[ToolSearch[None](), ScriptMode[None](dynamic_catalog=True)],
        )

        @agent.tool_plain(defer_loading=True)
        def weather(city: str) -> str:
            """Get the weather."""
            return f'sunny in {city}'

        result = await agent.run('what is the weather in Oslo?')
        assert result.output == "{'status': 'done', 'output': 'sunny in Oslo'}"
        assert all('async def' not in d for d in descriptions)
        assert len({d for d in descriptions}) == 1
        assert '`weather`' in prompts[1]

    async def test_announcement_names_the_callable_form(self):
        cap = ScriptMode[None](dynamic_catalog=True)
        ctx = run_context()
        await announce_local(cap, ctx, {'discovered_tools': [{'name': 'get-weather'}, {'name': 'github.me'}]})
        assert announcements(ctx) == [f'{ANNOUNCED}: `get_weather`, `github_me`.']

    async def test_upstream_instructions_keep_their_toolset_attribution(self):
        """Relaying through the base class keeps the wrapped toolset's id on its own instruction parts."""

        class Upstream(FunctionToolset[None]):
            async def get_instructions(self, ctx: RunContext[None]) -> Any:
                return 'crm rules'

        toolset = ScriptModeToolset(wrapped=Upstream([add], id='crm'), dynamic_catalog=True)
        ctx = run_context()
        await toolset.get_tools(ctx)
        instructions = await toolset.get_instructions(ctx)
        assert isinstance(instructions, list)
        first = instructions[0]
        assert isinstance(first, InstructionPart) and first.content == 'crm rules'
        assert first.id is not None and 'crm' in str(first.id.source)

    async def test_description_is_true_before_any_tool_is_folded(self):
        toolset = ScriptModeToolset(wrapped=FunctionToolset(), dynamic_catalog=True)
        description = (await toolset.get_tools(run_context()))[RUN_SCRIPT_TOOL_NAME].tool_def.description or ''
        assert 'no tool is callable yet' in description
        assert 'listed below' not in description

    async def test_search_addendum_when_search_tools_is_native(self):
        agent, _ = build_agent(extra=[ToolSearch()], dynamic_catalog=True)

        @agent.tool_plain(defer_loading=True)
        def later(x: int) -> int:
            """Only reachable through search."""
            return x

        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        tools = {t.name: t for t in model.last_model_request_parameters.function_tools}
        assert 'Use `search_tools` to discover more' in (tools[RUN_SCRIPT_TOOL_NAME].description or '')
        agent, _ = build_agent(dynamic_catalog=True)
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        assert 'search_tools' not in (model.last_model_request_parameters.function_tools[0].description or '')


class CloseStaleParams(TypedDict):
    repo: str


CLOSE_STALE = ScriptTool(
    'close_stale',
    """
# Close every stale issue in a repository
issues = await list_issues(repo=input.repo)
stale = [i for i in issues if i.stale]
closed = [await close_issue(repo=input.repo, number=i.number) for i in stale[:20]]
return {'closed': len(closed)}
""",
    parameters=CloseStaleParams,
    returns=dict[str, int],
)


class TestScriptTools:
    async def test_a_script_tool_is_folded_into_the_catalog_by_default(self):
        agent, _ = build_agent(scripts=[CLOSE_STALE])
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        defs = model.last_model_request_parameters.function_tools
        assert [d.name for d in defs] == [RUN_SCRIPT_TOOL_NAME]
        description = defs[0].description or ''
        assert 'async def close_stale(*, repo: str) -> dict[str, int]:' in description
        assert '"""Close every stale issue in a repository"""' in description

    async def test_a_predicate_makes_a_script_tool_native(self):
        def not_close_stale(ctx: RunContext[None], td: ToolDefinition) -> bool:
            return td.name != 'close_stale'

        agent, _ = build_agent(scripts=[CLOSE_STALE], tools=not_close_stale)
        model = await describe(agent)
        assert model.last_model_request_parameters is not None
        defs = {d.name: d for d in model.last_model_request_parameters.function_tools}
        assert set(defs) == {RUN_SCRIPT_TOOL_NAME, 'close_stale'}
        assert defs['close_stale'].description == 'Close every stale issue in a repository'
        assert defs['close_stale'].parameters_json_schema == {
            'type': 'object',
            'properties': {'repo': {'type': 'string'}},
            'required': ['repo'],
        }
        assert 'close_stale' not in (defs[RUN_SCRIPT_TOOL_NAME].description or '')
