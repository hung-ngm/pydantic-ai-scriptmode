"""ScriptMode under `TemporalDurability`: the engine runs workflow-side, folded calls are activities.

The plan is compiled, validated, and scheduled inside the workflow; every folded call goes through
the wrapped durable toolset, so it is an activity and the history replays. The tests start a local
Temporal dev server (`WorkflowEnvironment.start_local`, downloaded by the SDK on first use). The
harness requires this test shape of any capability that overrides `for_run`
(`agent_docs/review-checklist.md`, "Tests"); it mirrors `tests/code_mode/test_temporal.py` there.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

try:
    from pydantic_ai.durable_exec.temporal import AgentPlugin, PydanticAIPlugin, TemporalDurability
    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.common import RetryPolicy
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Replayer, Worker
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions
    from temporalio.workflow import ActivityConfig
except ImportError:  # pragma: no cover
    pytest.skip('temporalio not installed', allow_module_level=True)

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets.function import FunctionToolset

from pydantic_ai_scriptmode import ScriptMode

pytestmark = pytest.mark.anyio

TEMPORAL_PORT = 7245
TASK_QUEUE = 'pydantic-ai-scriptmode-queue'
ACTIVITY_CONFIG = ActivityConfig(
    start_to_close_timeout=timedelta(seconds=60),
    retry_policy=RetryPolicy(maximum_attempts=1),
)
SCRIPT = '# Add two numbers\nresult = await add(a=3, b=4)\nreturn result'
FAILING_SCRIPT = '# Add then double\nresult = await add(a=3, b=4)\ndoubled = await boom(n=result)\nreturn doubled'
CORRECTED_SCRIPT = '# Add then double\nresult = await add(a=3, b=4)\ndoubled = await twice(n=result)\nreturn doubled'


def _workflow_runner() -> SandboxedWorkflowRunner:
    # `pydantic_graph` is registered as a failure exception type by `PydanticAIPlugin` without being
    # passed through, so the sandbox imports it for real and trips on `opentelemetry.context`'s
    # `os.environ.get` at import time (pydantic/pydantic-ai#6986).
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules('coverage', 'pydantic_graph')
    )


@pytest.fixture(scope='module')
def anyio_backend() -> str:
    return 'asyncio'


@pytest.fixture(scope='module')
async def temporal_env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(  # pyright: ignore[reportUnknownMemberType]
        port=TEMPORAL_PORT,
        dev_server_extra_args=['--dynamic-config-value', 'frontend.enableServerVersionCheck=false'],
    ) as env:
        yield env


@pytest.fixture
async def client(temporal_env: WorkflowEnvironment) -> Client:
    return await Client.connect(f'localhost:{TEMPORAL_PORT}', plugins=[PydanticAIPlugin()])


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def twice(n: int) -> int:
    """Double a number."""
    return n * 2


def boom(n: int) -> int:
    """Fail every time."""
    raise RuntimeError('boom')


def _script_model(messages: list[ModelRequest | ModelResponse], info: AgentInfo) -> ModelResponse:
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_name == 'run_script':
                    content: Any = part.content
                    return ModelResponse(parts=[TextPart(content=f'done: {content["output"]}')])
    return ModelResponse(parts=[ToolCallPart(tool_name='run_script', args={'script': SCRIPT}, tool_call_id='tc_1')])


def _retrying_model(messages: list[ModelRequest | ModelResponse], info: AgentInfo) -> ModelResponse:
    """A script naming an unknown tool, then the corrected script, then the summary."""
    returns = [
        part
        for msg in messages
        if isinstance(msg, ModelRequest)
        for part in msg.parts
        if isinstance(part, (ToolReturnPart, RetryPromptPart)) and part.tool_name == 'run_script'
    ]
    if not returns:
        return ModelResponse(
            parts=[ToolCallPart(tool_name='run_script', args={'script': FAILING_SCRIPT}, tool_call_id='tc_1')]
        )
    if isinstance(returns[-1], RetryPromptPart):
        return ModelResponse(
            parts=[ToolCallPart(tool_name='run_script', args={'script': CORRECTED_SCRIPT}, tool_call_id='tc_2')]
        )
    content: Any = returns[-1].content
    return ModelResponse(parts=[TextPart(content=f'done: {content["output"]}')])


script_agent = Agent(
    FunctionModel(_script_model),
    name='script_mode_temporal_agent',
    toolsets=[FunctionToolset(tools=[add], id='math')],
    capabilities=[ScriptMode(), TemporalDurability(activity_config=ACTIVITY_CONFIG)],
)

retrying_agent = Agent(
    FunctionModel(_retrying_model),
    name='script_mode_retry_agent',
    toolsets=[FunctionToolset(tools=[add, twice, boom], id='math')],
    capabilities=[ScriptMode(), TemporalDurability(activity_config=ACTIVITY_CONFIG)],
)


@workflow.defn
class ScriptModeWorkflow:
    @workflow.run
    async def run(self, prompt: str) -> dict[str, Any]:
        result = await script_agent.run(prompt)
        return {'output': str(result.output), 'messages': result.all_messages_json().decode()}


@workflow.defn
class RetryingWorkflow:
    @workflow.run
    async def run(self, prompt: str) -> dict[str, Any]:
        result = await retrying_agent.run(prompt)
        return {'output': str(result.output), 'messages': result.all_messages_json().decode()}


async def test_script_mode_runs_in_temporal_workflow(client: Client) -> None:
    workflow_id = 'scriptmode_temporal_1'
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ScriptModeWorkflow],
        plugins=[AgentPlugin(script_agent)],
        workflow_runner=_workflow_runner(),
    ):
        result = await client.execute_workflow(
            ScriptModeWorkflow.run,
            args=['Calculate 3 + 4'],
            id=workflow_id,
            task_queue=TASK_QUEUE,
            execution_timeout=timedelta(seconds=30),
        )

    assert result['output'] == 'done: 7'
    messages = json.loads(result['messages'])
    assert [m['kind'] for m in messages] == ['request', 'response', 'request', 'response']
    tool_return = messages[2]['parts'][0]
    assert tool_return['tool_name'] == 'run_script'
    assert tool_return['content'] == {'status': 'done', 'output': 7}
    nested_call = next(iter(tool_return['metadata']['tool_calls'].values()))
    assert nested_call['tool_name'] == 'add'
    assert nested_call['args'] == {'a': 3, 'b': 4}

    history = await client.get_workflow_handle(workflow_id).fetch_history()
    activities = [
        e.activity_task_scheduled_event_attributes.activity_type.name
        for e in history.events
        if e.HasField('activity_task_scheduled_event_attributes')
    ]
    # The folded call ran as the wrapped toolset's activity, not workflow-side.
    assert activities == [
        'agent__script_mode_temporal_agent__model_request',
        'agent__script_mode_temporal_agent__toolset__math__call_tool',
        'agent__script_mode_temporal_agent__model_request',
    ]

    replay = await Replayer(
        workflows=[ScriptModeWorkflow], plugins=[PydanticAIPlugin()], workflow_runner=_workflow_runner()
    ).replay_workflow(history)
    assert replay.replay_failure is None


async def test_record_reuse_inside_a_temporal_workflow(client: Client) -> None:
    """The corrected script reuses the settled step: `add` is one activity across both scripts, and
    the history replays, so the record rebuilt workflow-side matches what the first run did."""
    workflow_id = 'scriptmode_temporal_retry'
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[RetryingWorkflow],
        plugins=[AgentPlugin(retrying_agent)],
        workflow_runner=_workflow_runner(),
    ):
        result = await client.execute_workflow(
            RetryingWorkflow.run,
            args=['Add then double'],
            id=workflow_id,
            task_queue=TASK_QUEUE,
            execution_timeout=timedelta(seconds=30),
        )

    assert result['output'] == 'done: 14'
    messages = json.loads(result['messages'])
    retry = messages[2]['parts'][0]
    assert retry['part_kind'] == 'retry-prompt'
    assert 'boom' in retry['content'] and 'result' in retry['content']
    second_return = messages[4]['parts'][0]
    assert second_return['content'] == {'status': 'done', 'output': 14}
    assert [c['tool_name'] for c in second_return['metadata']['tool_calls'].values()] == ['twice']

    history = await client.get_workflow_handle(workflow_id).fetch_history()
    activities = [
        e.activity_task_scheduled_event_attributes.activity_type.name
        for e in history.events
        if e.HasField('activity_task_scheduled_event_attributes')
    ]
    assert activities == [
        'agent__script_mode_retry_agent__model_request',
        'agent__script_mode_retry_agent__toolset__math__call_tool',  # add
        'agent__script_mode_retry_agent__toolset__math__call_tool',  # boom
        'agent__script_mode_retry_agent__model_request',
        'agent__script_mode_retry_agent__toolset__math__call_tool',  # twice; add reused from the record
        'agent__script_mode_retry_agent__model_request',
    ]

    replay = await Replayer(
        workflows=[RetryingWorkflow], plugins=[PydanticAIPlugin()], workflow_runner=_workflow_runner()
    ).replay_workflow(history)
    assert replay.replay_failure is None
