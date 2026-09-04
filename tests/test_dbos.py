"""ScriptMode under `DBOSDurability`: the engine runs workflow-side, the model requests are DBOS steps.

The agent and the workflow are module-level so DBOS registers them before `DBOS.launch()`. The
harness requires this test shape of any capability that overrides `for_run`
(`agent_docs/review-checklist.md`, "Tests"); it mirrors `tests/code_mode/test_dbos.py` there.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from typing import Any

import pytest

try:
    from dbos import DBOS, DBOSConfig, SetWorkflowID
    from pydantic_ai.durable_exec.dbos import DBOSDurability
except ImportError:  # pragma: no cover
    pytest.skip('dbos not installed', allow_module_level=True)

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets.function import FunctionToolset

from pydantic_ai_scriptmode import ScriptMode

# `run_sync` inside a DBOS workflow goes through `pydantic_graph`'s `get_event_loop`, which calls
# `asyncio.get_event_loop()` with no loop running; Python 3.12+ deprecates that. Not ours to fix.
pytestmark = pytest.mark.filterwarnings('ignore:There is no current event loop:DeprecationWarning')

SCRIPT = '# Add two numbers\nresult = await add(a=3, b=4)\nreturn result'


@pytest.fixture(scope='module')
def dbos_instance(tmp_path_factory: pytest.TempPathFactory) -> Generator[DBOS, Any, None]:
    dbos_sqlite_file = tmp_path_factory.mktemp('dbos') / 'dbostest.sqlite'
    dbos_config: DBOSConfig = {
        'name': 'scriptmode_dbos_tests',
        'system_database_url': f'sqlite:///{dbos_sqlite_file}',
        'run_admin_server': False,
        'enable_otlp': False,
    }
    dbos = DBOS(config=dbos_config)
    DBOS.launch()
    try:
        yield dbos
    finally:
        DBOS.destroy()


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def _script_model(messages: list[ModelRequest | ModelResponse], info: AgentInfo) -> ModelResponse:
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_name == 'run_script':
                    content: Any = part.content
                    return ModelResponse(parts=[TextPart(content=f'done: {content["output"]}')])
    return ModelResponse(parts=[ToolCallPart(tool_name='run_script', args={'script': SCRIPT}, tool_call_id='tc_1')])


script_agent = Agent(
    FunctionModel(_script_model),
    name='script_mode_dbos_agent',
    toolsets=[FunctionToolset(tools=[add], id='math')],
    capabilities=[ScriptMode(), DBOSDurability()],
)


@DBOS.workflow()
def run_script_agent(prompt: str) -> dict[str, Any]:
    result = script_agent.run_sync(prompt)
    return {'output': str(result.output), 'messages': result.all_messages_json().decode()}


def test_script_mode_runs_in_dbos_workflow(dbos_instance: DBOS) -> None:
    workflow_id = str(uuid.uuid4())
    with SetWorkflowID(workflow_id):
        payload = run_script_agent('Calculate 3 + 4')

    assert payload['output'] == 'done: 7'

    messages = json.loads(payload['messages'])
    assert [m['kind'] for m in messages] == ['request', 'response', 'request', 'response']
    tool_return = messages[2]['parts'][0]
    assert tool_return['tool_name'] == 'run_script'
    assert tool_return['content'] == {'status': 'done', 'output': 7}
    nested_call = next(iter(tool_return['metadata']['tool_calls'].values()))
    assert nested_call['tool_name'] == 'add'
    assert nested_call['args'] == {'a': 3, 'b': 4}

    steps = dbos_instance.list_workflow_steps(workflow_id)
    step_names = [step['function_name'] for step in steps]
    assert step_names.count('script_mode_dbos_agent__model.request') == 2
