"""Issue triage: close the stale issues in a repository with one script.

With plain tools the model pays a round trip per dependent stage: list the issues, then close each
one it picked. With `ScriptMode` it writes one script that lists, filters, returns early when there is
nothing to do, and fans out the closes; the whole task is one model request plus one final answer.

Run:  uv run examples/basic.py
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

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME, ScriptMode

load_dotenv()
DEFAULT_MODEL = os.environ.get('PYDANTIC_AI_MODEL', 'anthropic:claude-sonnet-5')

PROMPT = 'Close every stale issue in the api repository and tell me how many you closed.'


@dataclass
class Issue:
    """One issue in a repository."""

    number: int
    title: str
    stale: bool


# In-memory stand-ins for an issue tracker, so the example needs only a model key.
ISSUES: dict[str, list[Issue]] = {
    'api': [
        Issue(1, 'Timeout on large uploads', stale=True),
        Issue(2, 'Add rate limit headers', stale=False),
        Issue(3, 'Flaky auth test', stale=True),
    ],
}
CLOSED: list[int] = []

tools: FunctionToolset[None] = FunctionToolset()


@tools.tool_plain
async def list_issues(repo: str) -> list[Issue]:
    """Every open issue in a repository."""
    return ISSUES[repo]


@tools.tool_plain
async def close_issue(repo: str, number: int) -> str:
    """Close one issue."""
    CLOSED.append(number)
    return f'closed {repo}#{number}'


def build_agent(model: Model | str = DEFAULT_MODEL) -> Agent[None, str]:
    """An issue-triage agent whose two tools are folded into `run_script`."""
    return Agent(
        model,
        instructions='You triage issues for one team. Use run_script to do a whole task in one call. '
        'Reply with a one-line summary when done.',
        deps_type=type(None),
        toolsets=[tools],
        capabilities=[ScriptMode()],
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
    """Run the task once and show the script that did it."""
    result = await build_agent().run(PROMPT)
    show_scripts(result.all_messages())
    print(f'--- answer\n{result.output}')
    print(f'--- {result.usage.requests} model requests, closed {CLOSED}')


if __name__ == '__main__':
    asyncio.run(main())
