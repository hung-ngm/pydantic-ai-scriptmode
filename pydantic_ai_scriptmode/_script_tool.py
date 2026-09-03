"""A script tool: a script the developer saved under a name, compiled at construction (ADR 0005)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai_scriptmode._compile import compile_script
from pydantic_ai_scriptmode._plan import Plan


@dataclass(frozen=True)
class ScriptTool:
    """A saved script exposed as a tool; calling it runs the plan with the call's arguments bound as `input`.

    The script is compiled here, so a script that does not compile raises `CompileError` where the
    tool is defined, not when the model calls it.
    """

    name: str
    script: str
    description: str | None = None
    """What the model sees; defaults to the script's intent line."""
    plan: Plan = field(init=False)

    def __post_init__(self) -> None:
        plan = compile_script(self.script)
        object.__setattr__(self, 'plan', plan)
        if self.description is None:
            object.__setattr__(self, 'description', plan.intent)
