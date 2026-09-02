"""A spaced-practice tutor: four tools, one `run_script` call per task.

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
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

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

agent: Agent[None, str] = Agent(
    MODEL,
    deps_type=type(None),
    capabilities=[ScriptMode[None]()],
    instructions=(
        'You are a maths tutor managing one student. Use run_script to do a whole task in one call. '
        'Reply with a one-line summary when done.'
    ),
)


@agent.tool_plain
async def list_topics() -> list[Topic]:
    """Every topic in the syllabus."""
    return TOPICS


@agent.tool_plain
async def get_mastery(topic_id: str) -> Mastery:
    """The student's current mastery of one topic."""
    return Mastery(topic_id, SCORES[topic_id])


@agent.tool_plain
async def fetch_exercises(topic_id: str, n: int) -> list[Exercise]:
    """Up to n practice exercises for a topic. Fails if the topic has no exercise bank."""
    if topic_id in NO_BANK:
        raise RuntimeError(f'no exercise bank for {topic_id}')
    return [Exercise(f'{topic_id}-{i}', topic_id, f'{topic_id} exercise {i}') for i in range(1, n + 1)]


@agent.tool_plain
async def schedule_review(topic_id: str, days: int) -> str:
    """Schedule a review of a topic in a number of days."""
    scheduled.append((topic_id, days))
    return f'review of {topic_id} in {days} days'


TASKS = {
    'practice': "Build tonight's practice set: 5 exercises for each of the 3 weakest topics (mastery below 0.6). "
    'Skip a topic if its exercises cannot be fetched.',
    'reviews': 'Schedule a review in 2 days for every topic with mastery below 0.8. If none, say so.',
    'impossible': 'Email me a progress report.',
}


def show(messages: list[ModelMessage]) -> tuple[int, int]:
    """Print every script, retry, and return in the run; count the scripts and retries."""
    scripts = retries = 0
    for m in messages:
        if isinstance(m, ModelResponse):
            for p in m.parts:
                if isinstance(p, ToolCallPart) and p.tool_name == RUN_SCRIPT_TOOL_NAME:
                    scripts += 1
                    print(f'--- script {scripts}\n{p.args_as_dict()["script"]}')
        else:
            for p in m.parts:
                if isinstance(p, RetryPromptPart):
                    retries += 1
                    print(f'--- retry\n{p.model_response()}')
                elif isinstance(p, ToolReturnPart) and p.tool_name == RUN_SCRIPT_TOOL_NAME:
                    print(f'--- return\n{p.content}')
    return scripts, retries


async def main() -> None:
    """Run each task and print what the model wrote and what it got back."""
    random.seed(0)
    print(f'model: {MODEL}\n')
    wanted = sys.argv[1:] or list(TASKS)
    for name, prompt in ((n, TASKS[n]) for n in wanted):
        print(f'=== {name}: {prompt}')
        try:
            result = await agent.run(prompt)
        except Exception as e:  # noqa: BLE001 - the failure is the finding
            print(f'raised {type(e).__name__}: {e}\n')
            continue
        scripts, retries = show(result.all_messages())
        usage = result.usage
        print(f'--- answer\n{result.output}')
        print(
            f'--- {scripts} script(s), {retries} retry(ies), {usage.requests} model requests, {usage.total_tokens} tokens\n'
        )
    print(f'scheduled: {scheduled}')


if __name__ == '__main__':
    asyncio.run(main())
