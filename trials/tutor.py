"""A spaced-practice tutor: four tools, each task run with plain tools and then with ScriptMode.

The shape ScriptMode is for: fan out over a list, filter on what came back, act on the survivors.
Plain tool use pays a model round trip per call; a script pays one.

Run:  uv run python trials/tutor.py [task ...]   (tasks: practice, reviews, impossible, reset)
Reads ANTHROPIC_API_KEY from `.env` via python-dotenv; a standard workspace key, not an identity-linked
one. Override the model with PYDANTIC_AI_MODEL; set SCRIPTMODE_DYNAMIC_CATALOG=1 to trial the catalog in instructions.
The script agent also has one script tool, `weak_topics`; set SCRIPTMODE_NATIVE_SCRIPTS=1 to keep it native.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from dataclasses import dataclass
from typing import Any, cast

import logfire
from dotenv import load_dotenv
from pydantic_ai import Agent, ApprovalRequired, DeferredToolRequests, ModelRetry, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from typing_extensions import TypedDict

from pydantic_ai_scriptmode import RUN_SCRIPT_TOOL_NAME, ScriptMode, ScriptTool

load_dotenv()
MODEL = os.environ.get('PYDANTIC_AI_MODEL', 'anthropic:claude-opus-5')
DYNAMIC_CATALOG = os.environ.get('SCRIPTMODE_DYNAMIC_CATALOG', '') == '1'
NATIVE_SCRIPTS = os.environ.get('SCRIPTMODE_NATIVE_SCRIPTS', '') == '1'

logfire.configure(
    send_to_logfire='if-token-present',  # a clone without a token runs without prompting
    console=False,
    service_name='pydantic-ai-scriptmode-tutor',
    service_version='0.1.0',
    environment=os.environ.get('DEPLOYMENT_ENVIRONMENT', 'development'),
)
logfire.instrument_pydantic_ai()

AGENT_RUNS = logfire.metric_counter('scriptmode.agent.runs', unit='1')
MODEL_REQUESTS = logfire.metric_histogram('scriptmode.agent.model_requests', unit='1')
TOOL_CALLS = logfire.metric_histogram('scriptmode.agent.tool_calls', unit='1')
TOKENS = logfire.metric_histogram('scriptmode.agent.tokens', unit='1')

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
reset: list[str] = []
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


@tools.tool
async def reset_mastery(ctx: RunContext[None], topic_id: str) -> str:
    """Reset the student's mastery of a topic to zero. Needs the tutor's approval."""
    if not ctx.tool_call_approved:
        raise ApprovalRequired
    reset.append(topic_id)
    return f'reset {topic_id}'


# -- a saved script -------------------------------------------------------------------------------


class WeakTopicsParams(TypedDict):
    """Arguments of `weak_topics`."""

    threshold: float


WEAK_TOPICS = ScriptTool(
    'weak_topics',
    """
# The topics the student scores below a threshold on, weakest first
topics = await list_topics()
mastery = [await get_mastery(topic_id=t.id) for t in topics[:20]]
weak = [m for m in mastery if m.score < input.threshold]
return sorted(weak, key=lambda m: m.score)
""",
    parameters=WeakTopicsParams,
    returns=list[Mastery],
)


def not_script_tools(ctx: RunContext[None], td: ToolDefinition) -> bool:
    """Keep the script tools native; every other tool is folded."""
    return not (td.metadata or {}).get('script_mode', False)


INSTRUCTIONS = 'You are a maths tutor managing one student. Reply with a one-line summary when done.'

# The same tools, two ways: called one by one, or folded behind `run_script`.
Output = str | DeferredToolRequests
plain_agent: Agent[None, Output] = Agent(
    MODEL, deps_type=type(None), output_type=[str, DeferredToolRequests], toolsets=[tools], instructions=INSTRUCTIONS
)
script_agent: Agent[None, Output] = Agent(
    MODEL,
    deps_type=type(None),
    output_type=[str, DeferredToolRequests],
    toolsets=[tools],
    capabilities=[
        ScriptMode[None](
            tools=not_script_tools if NATIVE_SCRIPTS else 'all', dynamic_catalog=DYNAMIC_CATALOG, scripts=[WEAK_TOPICS]
        )
    ],
    instructions=INSTRUCTIONS + ' Use run_script to do a whole task in one call.',
)


TASKS = {
    'practice': "Build tonight's practice set: 5 exercises for each of the 3 weakest topics (mastery below 0.6). "
    'Skip a topic if its exercises cannot be fetched.',
    'reviews': 'Schedule a review in 2 days for every topic with mastery below 0.8. If none, say so.',
    'impossible': 'Email me a progress report.',
    'reset': 'Reset mastery for every topic the student scores below 0.5 on, so they start those over.',
}


@dataclass
class Stats:
    """What one run cost."""

    requests: int
    tool_calls: int
    retries: int
    tokens: int


def nested_calls(metadata: Any) -> int:
    """Tool calls a script made. A script tool it called counts as the calls inside it, not as one more."""
    if not isinstance(metadata, dict) or 'tool_calls' not in metadata:
        return 0
    data = cast(dict[str, Any], metadata)
    calls = cast(dict[str, ToolCallPart], data['tool_calls'])
    returns = cast(dict[str, ToolReturnPart], data.get('tool_returns', {}))
    return sum(1 if returns.get(call_id) is None else calls_behind(returns[call_id]) for call_id in calls)


def calls_behind(part: ToolReturnPart) -> int:
    """One for a plain tool; for a script tool, the calls its saved script made."""
    metadata: Any = part.metadata
    if isinstance(metadata, dict) and cast(dict[str, Any], metadata).get('script_tool'):
        return nested_calls(metadata)
    return 1


def show(messages: list[ModelMessage], usage: RunUsage) -> Stats:
    """Print every script, retry, and return in the run; count what it cost."""
    scripts = retries = tool_calls = 0
    for m in messages:
        if isinstance(m, ModelResponse):
            for p in m.parts:
                if isinstance(p, ToolCallPart) and p.tool_name == RUN_SCRIPT_TOOL_NAME:
                    scripts += 1
                    print(f'--- script {scripts}\n{p.args_as_dict()["script"]}')
                elif isinstance(p, ToolCallPart) and p.tool_name == WEAK_TOPICS.name:
                    print(f'--- native script tool call: {p.tool_name} {p.args_as_dict()}')  # counted by its return
                elif isinstance(p, ToolCallPart):
                    tool_calls += 1
        else:
            for p in m.parts:
                if isinstance(p, RetryPromptPart):
                    retries += 1
                    print(f'--- retry\n{p.model_response()}')
                elif isinstance(p, ToolReturnPart) and p.tool_name == RUN_SCRIPT_TOOL_NAME:
                    print(f'--- return\n{p.content}')
                    tool_calls += nested_calls(p.metadata)
                elif isinstance(p, ToolReturnPart) and p.tool_name == WEAK_TOPICS.name:
                    tool_calls += nested_calls(p.metadata)
    return Stats(usage.requests, tool_calls, retries, usage.total_tokens)


async def run_task(agent: Agent[None, Output], label: str, prompt: str) -> Stats | None:
    """Run one task on one agent and print the trace; approve every approval request and continue."""
    print(f'--- [{label}]')
    usage = RunUsage()
    try:
        result = await agent.run(prompt)
        usage.incr(result.usage)
        while isinstance(result.output, DeferredToolRequests):
            for call in result.output.approvals:
                print(f'--- approval requested: {call.tool_name} {result.output.metadata.get(call.tool_call_id, {})}')
            result = await agent.run(
                message_history=result.all_messages(),
                deferred_tool_results=result.output.build_results(approve_all=True),
            )
            usage.incr(result.usage)
    except Exception as e:  # noqa: BLE001 - the failure is the finding
        logfire.exception('Tutor run failed in {mode}', mode=label, model=MODEL)
        print(f'raised {type(e).__name__}: {e}\n')
        return None
    stats = show(result.all_messages(), usage)
    metric_attributes = {'mode': label, 'model': MODEL}
    AGENT_RUNS.add(1, metric_attributes)
    MODEL_REQUESTS.record(stats.requests, metric_attributes)
    TOOL_CALLS.record(stats.tool_calls, metric_attributes)
    TOKENS.record(stats.tokens, metric_attributes)
    logfire.info(
        'Tutor run completed in {mode}: {requests} model requests, {tool_calls} tool calls, {tokens} tokens',
        mode=label,
        model=MODEL,
        requests=stats.requests,
        tool_calls=stats.tool_calls,
        tokens=stats.tokens,
    )
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
        reset.clear()
        plain = await run_task(plain_agent, 'plain tools', prompt)
        scheduled.clear()
        reset.clear()
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
