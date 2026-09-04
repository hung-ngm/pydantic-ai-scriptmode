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

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME, SQLiteRecordStore

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
    assert [path.name for path in EXAMPLE_FILES] == ['approval.py', 'basic.py', 'engine.py', 'script_tool.py']


@pytest.mark.parametrize('path', EXAMPLE_FILES, ids=lambda p: p.stem)
def test_example_builds_agent(path: Path):
    if path.stem == 'engine':
        pytest.skip('no agent: the engine example runs without one')
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


async def test_approval_parks_on_the_payments_and_the_approved_run_pays_only_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    approval = load('approval')
    monkeypatch.setattr(approval, 'STATE_DIR', tmp_path)
    model = script_model(
        """
# Pay the overdue invoices under 5000 from verified vendors
invoices = await list_invoices()
due = [i for i in invoices if i.overdue and i.amount < 5000]
vendors = [await get_vendor(vendor_id=i.vendor_id) for i in due[:20]]
verified = [i for i, v in zip(due, vendors) if v.verified]
if len(verified) == 0:
    return 'nothing to pay'
paid = [await pay_invoice(invoice_id=i.id, amount=i.amount, _reason='overdue, verified vendor') for i in verified[:20]]
return paid
"""
    )
    store = SQLiteRecordStore(tmp_path / 'records.sqlite')
    try:
        # First process: the run parks, nothing is paid, and the resume material is on disk.
        await approval.start(approval.build_agent(model=model, store=store))
        assert approval.PAID == []
        assert (tmp_path / 'messages.json').exists() and (tmp_path / 'requests.json').exists()
        out = capsys.readouterr().out
        assert "needs approval: pay_invoice {'invoice_id': 'inv-1', 'amount': 1200.0} (overdue, verified vendor)" in out
        assert 'inv-5' in out and 'inv-2' not in out and 'inv-3' not in out
        # Second process: a new agent on the same store pays the parked invoices and re-lists nothing.
        await approval.resume(approval.build_agent(model=model, store=store))
    finally:
        store.close()
    assert approval.PAID == [('inv-1', 1200.0), ('inv-5', 990.0)]
    assert approval.CALLS == ['list_invoices', 'get_vendor', 'get_vendor', 'get_vendor', 'pay_invoice', 'pay_invoice']
    assert 'paid inv-1: 1200.00' in capsys.readouterr().out


async def test_engine_runs_the_script_without_an_agent():
    engine = load('engine')
    result = await engine.run()
    assert result.status == 'done'
    assert result.output == {'London': 'cloudy', 'Paris': 'sunny', 'Tokyo': 'sunny'}
    assert [(name, step.status) for name, step in result.record.steps.items()] == [
        ('cities', 'done'),
        ('coords', 'done'),
        ('reports', 'done'),
    ]


async def test_engine_reports_a_validation_issue():
    engine = load('engine')
    with pytest.raises(ValueError, match='get_forecast'):
        await engine.run('x = await get_forecast(city=1)\nreturn x')


async def test_script_tool_runs_the_saved_sweep_from_a_script():
    script_tool = load('script_tool')
    agent = script_tool.build_agent(
        model=script_model(
            """
# Run the restock sweep at 20 units
orders = await restock_low(threshold=20)
return orders
"""
        )
    )
    result = await agent.run(script_tool.PROMPT)
    assert script_tool.ORDERS == [('mug-01', 50), ('cap-01', 40)]
    assert "'ordered 50 of mug-01'" in result.output
