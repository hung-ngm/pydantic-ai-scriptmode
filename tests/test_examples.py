"""The `examples/` scripts, built with `TestModel` and driven offline by a `FunctionModel` that writes the script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME

pytestmark = pytest.mark.anyio

EXAMPLES_DIR = Path(__file__).parent.parent / 'examples'
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob('*.py'))


def load(name: str) -> ModuleType:
    """Import `examples/<name>.py` afresh, so its in-memory data starts clean."""
    path = EXAMPLES_DIR / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'examples_{name}', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def script_model(*scripts: str) -> FunctionModel:
    """A model that answers each request with the next script, then with the last tool return as text."""
    remaining = list(scripts)

    async def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if remaining:
            return ModelResponse(parts=[ToolCallPart(RUN_SCRIPT_TOOL_NAME, {'script': remaining.pop(0)})])
        last = messages[-1].parts[-1]
        assert isinstance(last, ToolReturnPart)
        return ModelResponse(parts=[TextPart(str(last.content))])

    return FunctionModel(model)


def test_examples_present():
    assert [path.name for path in EXAMPLE_FILES] == ['basic.py']


@pytest.mark.parametrize('path', EXAMPLE_FILES, ids=lambda p: p.stem)
def test_example_builds_agent(path: Path):
    agent = load(path.stem).build_agent(model=TestModel())
    assert isinstance(agent, Agent)


async def test_basic_closes_the_stale_issues():
    basic = load('basic')
    agent = basic.build_agent(
        model=script_model(
            """
# Close the stale issues in api and count them
issues = await list_issues(repo='api')
stale = [i for i in issues if i.stale]
if len(stale) == 0:
    return {'closed': 0}
closed = [await close_issue(repo='api', number=i.number) for i in stale[:20]]
return {'closed': len(closed)}
"""
        )
    )
    result = await agent.run(basic.PROMPT)
    assert basic.CLOSED == [i.number for i in basic.ISSUES['api'] if i.stale]
    assert "'closed': 2" in result.output
