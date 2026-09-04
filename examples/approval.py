"""Accounts payable: payments park on approval, and the approved re-run resumes from the record.

`pay_invoice` raises `ApprovalRequired`, so a script that reaches it parks: the steps that settled are
kept in the record, the run returns `DeferredToolRequests` naming every parked payment, and nothing is
paid. The controller approves later, from another process; `SQLiteRecordStore` is what lets the
resumed run find the record, and only the parked payments are dispatched again.

Run:  uv run examples/approval.py             # parks on the payments and saves what a resume needs
      uv run examples/approval.py --approve   # approves them and pays
Reads ANTHROPIC_API_KEY from the environment or `.env`. Set PYDANTIC_AI_MODEL=provider:model to use
another model; you then need that provider's key instead.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic import TypeAdapter
from pydantic_ai import Agent, ApprovalRequired, DeferredToolRequests, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME, RecordStore, ScriptMode, SQLiteRecordStore

load_dotenv()
DEFAULT_MODEL = os.environ.get('PYDANTIC_AI_MODEL', 'anthropic:claude-sonnet-5')

PROMPT = 'Pay every overdue invoice under 5,000 whose vendor is verified, and tell me what you paid.'
STATE_DIR = Path(__file__).resolve().parent.parent / '.local' / 'approval'
"""Where the parked run keeps its messages, the approval request, and the record store."""
REQUESTS = TypeAdapter(DeferredToolRequests)


@dataclass
class Invoice:
    """One supplier invoice."""

    id: str
    vendor_id: str
    amount: float
    overdue: bool


@dataclass
class Vendor:
    """One supplier."""

    id: str
    name: str
    verified: bool
    """Whether the supplier's bank details have been verified."""


# In-memory stand-ins for an accounts-payable system, so the example needs only a model key.
INVOICES = [
    Invoice('inv-1', 'acme', 1200.0, overdue=True),
    Invoice('inv-2', 'acme', 7800.0, overdue=True),
    Invoice('inv-3', 'globex', 450.0, overdue=True),
    Invoice('inv-4', 'initech', 3100.0, overdue=False),
    Invoice('inv-5', 'initech', 990.0, overdue=True),
]
VENDORS = {
    'acme': Vendor('acme', 'Acme Supplies', verified=True),
    'globex': Vendor('globex', 'Globex Ltd', verified=False),
    'initech': Vendor('initech', 'Initech', verified=True),
}
PAID: list[tuple[str, float]] = []
CALLS: list[str] = []
"""Every tool call made, in order: the resumed run adds only the payments, the rest it reuses from the record."""

tools: FunctionToolset[None] = FunctionToolset()


@tools.tool_plain
async def list_invoices() -> list[Invoice]:
    """Every unpaid invoice."""
    CALLS.append('list_invoices')
    return INVOICES


@tools.tool_plain
async def get_vendor(vendor_id: str) -> Vendor:
    """One supplier."""
    CALLS.append('get_vendor')
    return VENDORS[vendor_id]


@tools.tool
async def pay_invoice(ctx: RunContext[None], invoice_id: str, amount: float) -> str:
    """Pay one invoice. Needs the controller's approval."""
    if not ctx.tool_call_approved:
        raise ApprovalRequired
    CALLS.append('pay_invoice')
    PAID.append((invoice_id, amount))
    return f'paid {invoice_id}: {amount:.2f}'


def build_agent(
    model: Model | str = DEFAULT_MODEL, store: RecordStore | None = None
) -> Agent[None, str | DeferredToolRequests]:
    """An accounts-payable agent; `DeferredToolRequests` among the outputs is what lets a run park."""
    return Agent(
        model,
        deps_type=type(None),
        output_type=[str, DeferredToolRequests],
        instructions='You run accounts payable for one company. Use run_script to do a whole task in one call. '
        'Reply with a one-line summary when done.',
        toolsets=[tools],
        capabilities=[ScriptMode(record_store=store or SQLiteRecordStore(STATE_DIR / 'records.sqlite'))],
    )


def show_scripts(messages: list[ModelMessage]) -> None:
    """Print each script the model wrote, what it got back, and any retry in between."""
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_name == RUN_SCRIPT_TOOL_NAME:
                print(f'--- script\n{part.args_as_dict()["script"]}')
            elif isinstance(part, ToolReturnPart) and part.tool_name == RUN_SCRIPT_TOOL_NAME:
                print(f'--- return\n{part.content}')
            elif isinstance(part, RetryPromptPart):
                print(f'--- retry\n{part.model_response()}')


async def start(agent: Agent[None, str | DeferredToolRequests]) -> None:
    """Run the task; when it parks on the payments, save what the resume needs and say what is waiting."""
    result = await agent.run(PROMPT)
    show_scripts(result.all_messages())
    if not isinstance(result.output, DeferredToolRequests):
        print(f'--- answer (nothing needed approval)\n{result.output}')
        return
    for call in result.output.approvals:
        for parked in result.output.metadata[call.tool_call_id]['suspended']:
            reason = f' ({parked["reason"]})' if parked['reason'] else ''
            print(f'--- needs approval: {parked["tool"]} {parked["args"]}{reason}')
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / 'messages.json').write_bytes(ModelMessagesTypeAdapter.dump_json(result.all_messages()))
    (STATE_DIR / 'requests.json').write_bytes(REQUESTS.dump_json(result.output))
    print(f'--- parked after {result.usage.requests} model requests; run again with --approve to pay')


async def resume(agent: Agent[None, str | DeferredToolRequests]) -> None:
    """Approve every parked payment and continue the saved conversation; only the payments run again."""
    messages = ModelMessagesTypeAdapter.validate_json((STATE_DIR / 'messages.json').read_bytes())
    requests = REQUESTS.validate_json((STATE_DIR / 'requests.json').read_bytes())
    result = await agent.run(message_history=messages, deferred_tool_results=requests.build_results(approve_all=True))
    show_scripts(result.new_messages())
    print(f'--- answer\n{result.output}')
    print(f'--- {result.usage.requests} model requests; tool calls this run: {CALLS}; paid {PAID}')


async def main() -> None:
    """Park on the first invocation, resume on the second."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    store = SQLiteRecordStore(STATE_DIR / 'records.sqlite')
    try:
        agent = build_agent(store=store)
        await (resume(agent) if '--approve' in sys.argv[1:] else start(agent))
    finally:
        store.close()


if __name__ == '__main__':
    asyncio.run(main())
