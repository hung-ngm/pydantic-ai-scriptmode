"""The engine alone: compile, validate, and execute a script against plain async functions.

No `Agent`, no model, no key. The three stages a `run_script` call goes through are public functions,
so a host that already has a script (from a model, a file, or a person) can run it against its own
functions; `dispatch` is the only way a plan reaches one.

Run:  uv run examples/engine.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic_ai_scriptmode import (
    CallStep,
    ExecuteResult,
    Limits,
    ToolSignature,
    compile_script,
    execute_plan,
    validate_plan,
)

SCRIPT = """
# The weather in each city, by name
cities = ['London', 'Paris', 'Tokyo']
coords = [await get_lat_lng(location=c) for c in cities]
reports = [await get_weather(lat=p.lat, lng=p.lng) for p in coords[:3]]
return {c: r.description for c, r in zip(cities, reports)}
"""

# What a real host would look up; here fixed so the example is deterministic.
COORDS = {'London': (51.5, -0.1), 'Paris': (48.9, 2.4), 'Tokyo': (35.7, 139.7)}


async def get_lat_lng(location: str) -> dict[str, float]:
    """Coordinates of a place."""
    lat, lng = COORDS[location]
    return {'lat': lat, 'lng': lng}


async def get_weather(lat: float, lng: float) -> dict[str, Any]:
    """The weather at coordinates."""
    return {'temperature_c': round(20 - abs(lat) / 5, 1), 'description': 'sunny' if lng > 0 else 'cloudy'}


FUNCTIONS = {'get_lat_lng': get_lat_lng, 'get_weather': get_weather}
SIGNATURES = {
    'get_lat_lng': ToolSignature('get_lat_lng', frozenset({'location'}), frozenset({'location'})),
    'get_weather': ToolSignature('get_weather', frozenset({'lat', 'lng'}), frozenset({'lat', 'lng'})),
}


async def dispatch(step: CallStep, args: dict[str, Any], *, resolution: Any = None) -> Any:
    """Perform one call of the plan. `resolution` is only set when re-entering a parked step."""
    return await FUNCTIONS[step.tool](**args)


async def run(script: str = SCRIPT) -> ExecuteResult:
    """Compile, validate, and execute `script`; raise on the first stage that rejects it."""
    plan = compile_script(script)  # CompileError carries every issue at once
    issues = validate_plan(plan, tools=SIGNATURES, limits=Limits())
    if issues:
        raise ValueError('\n'.join(issue.render() for issue in issues))
    return await execute_plan(plan, dispatch=dispatch)


async def main() -> None:
    """Run the script and show its output and how each step settled."""
    result = await run()
    print(f'--- output ({result.status})\n{result.output}')
    print('--- record')
    for name, step in result.record.steps.items():
        print(f'{name}: {step.status}')


if __name__ == '__main__':
    asyncio.run(main())
