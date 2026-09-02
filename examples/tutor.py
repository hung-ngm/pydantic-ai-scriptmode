"""A spaced-practice tutor: four tools, each task run with plain tools and then with ScriptMode.

The shape ScriptMode is for: fan out over a list, filter on what came back, act on the survivors.
Plain tool use pays a model round trip per call; a script pays one.

Run:  uv run python examples/tutor.py [task ...]   (tasks: practice, reviews, impossible)
Reads ANTHROPIC_API_KEY from `.env` via python-dotenv; a standard workspace key, not an identity-linked
one. Override the model with SCRIPTMODE_TRIAL_MODEL.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from dataclasses import dataclass

from dotenv import load_dotenv
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME, ScriptMode

load_dotenv()
MODEL = os.environ.get('SCRIPTMODE_TRIAL_MODEL', 'anthropic:claude-opus-5')

# -- the store -----------------------------------------------------------------------------------


@dataclass
class Topic:
    """One syllabus topic."""

    id: str
    name: str


@dataclass
class Mastery:
    """How well the student knows one topic."""

    topic_id: str
    score: float
    """0 to 1; below 0.6 is weak, below 0.8 is due for review."""


@dataclass
class Exercise:
    """One practice exercise."""

    id: str
    topic_id: str
    prompt: str


TOPICS = [
    Topic('fractions', 'Fractions'),
    Topic('decimals', 'Decimals'),
    Topic('percent', 'Percentages'),
    Topic('ratio', 'Ratios'),
    Topic('algebra-1', 'Linear equations'),
    Topic('geometry-1', 'Angles'),
    Topic('stats-1', 'Mean and median'),
    Topic('primes', 'Prime numbers'),
]
SCORES = {
    'fractions': 0.45,
    'decimals': 0.9,
    'percent': 0.55,
    'ratio': 0.7,
    'algebra-1': 0.3,
    'geometry-1': 0.85,
    'stats-1': 0.95,
    'primes': 0.6,
}
NO_BANK = {'algebra-1'}  # fetch_exercises fails for this topic
scheduled: list[tuple[str, int]] = []

tools: FunctionToolset[None] = FunctionToolset()


@tools.tool_plain
async def list_topics() -> list[Topic]:
    """Every topic in the syllabus."""
    return TOPICS


@tools.tool_plain
async def get_mastery(topic_id: str) -> Mastery:
    """The student's current mastery of one topic."""
    return Mastery(topic_id, SCORES[topic_id])


@tools.tool_plain
async def fetch_exercises(topic_id: str, n: int) -> list[Exercise]:
    """Up to n practice exercises for a topic. Fails if the topic has no exercise bank."""
    if topic_id in NO_BANK:
        raise ModelRetry(f'no exercise bank for {topic_id}')  # recoverable in both modes
    return [Exercise(f'{topic_id}-{i}', topic_id, f'{topic_id} exercise {i}') for i in range(1, n + 1)]


@tools.tool_plain
async def schedule_review(topic_id: str, days: int) -> str:
    """Schedule a review of a topic in a number of days."""
    scheduled.append((topic_id, days))
    return f'review of {topic_id} in {days} days'


INSTRUCTIONS = 'You are a maths tutor managing one student. Reply with a one-line summary when done.'

# The same tools, two ways: called one by one, or folded behind `run_script`.
plain_agent: Agent[None, str] = Agent(MODEL, deps_type=type(None), toolsets=[tools], instructions=INSTRUCTIONS)
script_agent: Agent[None, str] = Agent(
    MODEL,
    deps_type=type(None),
    toolsets=[tools],
    capabilities=[ScriptMode[None]()],
    instructions=INSTRUCTIONS + ' Use run_script to do a whole task in one call.',
)


TASKS = {
    'practice': "Build tonight's practice set: 5 exercises for each of the 3 weakest topics (mastery below 0.6). "
    'Skip a topic if its exercises cannot be fetched.',
    'reviews': 'Schedule a review in 2 days for every topic with mastery below 0.8. If none, say so.',
    'impossible': 'Email me a progress report.',
}


@dataclass
class Stats:
    """What one run cost."""

    requests: int
    tool_calls: int
    retries: int
    tokens: int


def show(messages: list[ModelMessage], usage: RunUsage) -> Stats:
    """Print every script, retry, and return in the run; count what it cost."""
    scripts = retries = tool_calls = 0
    for m in messages:
        if isinstance(m, ModelResponse):
            for p in m.parts:
                if isinstance(p, ToolCallPart) and p.tool_name == RUN_SCRIPT_TOOL_NAME:
                    scripts += 1
                    print(f'--- script {scripts}\n{p.args_as_dict()["script"]}')
                elif isinstance(p, ToolCallPart):
                    tool_calls += 1
        else:
            for p in m.parts:
                if isinstance(p, RetryPromptPart):
                    retries += 1
                    print(f'--- retry\n{p.model_response()}')
                elif isinstance(p, ToolReturnPart) and p.tool_name == RUN_SCRIPT_TOOL_NAME:
                    print(f'--- return\n{p.content}')
                    tool_calls += len(p.metadata['tool_calls']) if p.metadata else 0
    return Stats(usage.requests, tool_calls, retries, usage.total_tokens)


async def run_task(agent: Agent[None, str], label: str, prompt: str) -> Stats | None:
    """Run one task on one agent and print the trace."""
    print(f'--- [{label}]')
    try:
        result = await agent.run(prompt)
    except Exception as e:  # noqa: BLE001 - the failure is the finding
        print(f'raised {type(e).__name__}: {e}\n')
        return None
    stats = show(result.all_messages(), result.usage)
    print(f'--- answer\n{result.output}')
    print(
        f'--- {stats.requests} model requests, {stats.tool_calls} tool calls, {stats.retries} retries, {stats.tokens} tokens\n'
    )
    return stats


async def main() -> None:
    """Run each task both ways and print a comparison."""
    random.seed(0)
    print(f'model: {MODEL}\n')
    wanted = sys.argv[1:] or list(TASKS)
    rows: list[tuple[str, Stats | None, Stats | None]] = []
    for name in wanted:
        prompt = TASKS[name]
        print(f'=== {name}: {prompt}')
        scheduled.clear()
        plain = await run_task(plain_agent, 'plain tools', prompt)
        scheduled.clear()
        script = await run_task(script_agent, 'script mode', prompt)
        rows.append((name, plain, script))

    def cell(s: Stats | None) -> str:
        return 'failed' if s is None else f'{s.requests} req / {s.tool_calls} calls / {s.tokens} tok'

    print('=== comparison (model requests / tool calls / total tokens)')
    print(f'{"task":<12} {"plain tools":<34} {"script mode":<34}')
    for name, plain, script in rows:
        print(f'{name:<12} {cell(plain):<34} {cell(script):<34}')


if __name__ == '__main__':
    asyncio.run(main())
