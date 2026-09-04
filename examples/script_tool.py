"""Inventory: a restock sweep saved as a script tool, so the model calls it instead of writing it.

A script that worked once can be kept. `restock_low` below is the weekly sweep an operator would
otherwise re-prompt for: list the products, check each one's stock, reorder what is low. Saved as a
`ScriptTool` it is served to the model as one tool with a typed signature, and by default it is folded
into the catalog next to the tools it composes, so a script can call it too.

Run:  uv run examples/script_tool.py
Reads ANTHROPIC_API_KEY from the environment or `.env`. Set PYDANTIC_AI_MODEL=provider:model to use
another model; you then need that provider's key instead.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset
from typing_extensions import TypedDict

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME, ScriptMode, ScriptTool

load_dotenv()
DEFAULT_MODEL = os.environ.get('PYDANTIC_AI_MODEL', 'anthropic:claude-sonnet-5')

PROMPT = 'Run the restock sweep for the warehouse with a threshold of 20 units and tell me what was reordered.'


@dataclass
class Product:
    """One product in the catalogue."""

    sku: str
    name: str
    reorder_quantity: int
    """How many units one purchase order brings in."""


@dataclass
class Stock:
    """Units of one product on hand."""

    sku: str
    units: int


# In-memory stand-ins for an inventory system, so the example needs only a model key.
PRODUCTS = [
    Product('mug-01', 'Stoneware mug', reorder_quantity=50),
    Product('tee-m', 'T-shirt, medium', reorder_quantity=100),
    Product('cap-01', 'Cap', reorder_quantity=40),
    Product('bag-01', 'Tote bag', reorder_quantity=60),
]
UNITS = {'mug-01': 8, 'tee-m': 120, 'cap-01': 15, 'bag-01': 35}
ORDERS: list[tuple[str, int]] = []

tools: FunctionToolset[None] = FunctionToolset()


@tools.tool_plain
async def list_products() -> list[Product]:
    """Every product in the catalogue."""
    return PRODUCTS


@tools.tool_plain
async def get_stock(sku: str) -> Stock:
    """Units on hand for one product."""
    return Stock(sku, UNITS[sku])


@tools.tool_plain
async def reorder(sku: str, quantity: int) -> str:
    """Raise a purchase order for one product."""
    ORDERS.append((sku, quantity))
    return f'ordered {quantity} of {sku}'


class RestockParams(TypedDict):
    """Arguments of `restock_low`."""

    threshold: int
    """Reorder every product with fewer units than this on hand."""


# The saved script. It runs with the call's arguments bound as `input`, may call the three tools
# above, and returns the plan's output. Low means strictly below the threshold; the order size is the
# catalogue's, so the model never has to decide a quantity.
RESTOCK_SCRIPT = """
# Reorder every product whose stock is below input.threshold, at its catalogue quantity
products = await list_products()
stock = [await get_stock(sku=p.sku) for p in products[:50]]
low = [p for p, s in zip(products, stock) if s.units < input.threshold]
orders = [await reorder(sku=p.sku, quantity=p.reorder_quantity) for p in low[:50]]
return orders
"""

restock_low = ScriptTool(
    'restock_low',
    RESTOCK_SCRIPT,
    parameters=RestockParams,
    returns=list[str],
)


def build_agent(model: Model | str = DEFAULT_MODEL) -> Agent[None, str]:
    """An inventory agent with three tools and one saved script, all folded into `run_script`."""
    return Agent(
        model,
        deps_type=type(None),
        instructions='You run inventory for one warehouse. Use run_script to do a whole task in one call. '
        'Reply with a one-line summary when done.',
        toolsets=[tools],
        capabilities=[ScriptMode(scripts=[restock_low])],
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


async def main() -> None:
    """Run the sweep once and show the script that called it."""
    result = await build_agent().run(PROMPT)
    show_scripts(result.all_messages())
    print(f'--- answer\n{result.output}')
    print(f'--- {result.usage.requests} model requests, orders {ORDERS}')


if __name__ == '__main__':
    asyncio.run(main())
