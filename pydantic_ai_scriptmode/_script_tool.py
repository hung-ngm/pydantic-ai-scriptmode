"""A script tool: a script the developer saved under a name, compiled at construction (ADR 0005)."""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass, field
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai.tools import GenerateToolJsonSchema
from pydantic_core import to_jsonable_python

from pydantic_ai_scriptmode._compile import compile_script
from pydantic_ai_scriptmode._plan import Plan
from pydantic_ai_scriptmode._validate import input_fields

JsonSchema = dict[str, Any]

_NO_PARAMETERS: JsonSchema = {'type': 'object', 'properties': {}}


@dataclass(frozen=True)
class ScriptTool:
    """A saved script exposed as a tool; calling it runs the plan with the call's arguments bound as `input`.

    The script is compiled here, so a script that does not compile raises `CompileError` where the
    tool is defined, not when the model calls it.
    """

    name: str
    script: str
    _: KW_ONLY
    description: str | None = None
    """What the model sees; defaults to the script's intent line."""
    parameters: type[Any] | JsonSchema | None = None
    """The arguments the tool takes, as a Python type (validated) or a JSON schema (passed through)."""
    returns: type[Any] | None = None
    """The return type, rendered into the signature the model sees."""
    plan: Plan = field(init=False)
    parameters_json_schema: JsonSchema = field(init=False)
    return_schema: JsonSchema | None = field(init=False)
    _adapter: TypeAdapter[Any] | None = field(init=False, default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        plan = compile_script(self.script)
        object.__setattr__(self, 'plan', plan)
        if self.description is None:
            object.__setattr__(self, 'description', plan.intent)
        if self.parameters is None:
            schema = dict(_NO_PARAMETERS)
        elif isinstance(self.parameters, dict):
            schema = self.parameters
        else:
            adapter: TypeAdapter[Any] = TypeAdapter(self.parameters)
            object.__setattr__(self, '_adapter', adapter)
            schema = _schema(adapter)
        object.__setattr__(self, 'parameters_json_schema', schema)
        self._check_input_fields(schema)
        returns = None if self.returns is None else _schema(TypeAdapter(self.returns))
        object.__setattr__(self, 'return_schema', returns)

    def _check_input_fields(self, schema: JsonSchema) -> None:
        """Every `input.<field>` the script reads must be a declared parameter, unless the schema is open."""
        if schema.get('additionalProperties', False) is not False:
            return
        declared: set[str] = set(schema.get('properties', {}))
        unknown = sorted(input_fields(self.plan) - declared)
        if not unknown:
            return
        have = f'declared: {", ".join(sorted(declared))}' if declared else 'the tool declares no parameters'
        raise ValueError(
            f'script tool `{self.name}` reads {", ".join(f"`input.{f}`" for f in unknown)}, '
            f'which {"is" if len(unknown) == 1 else "are"} not among its parameters ({have}). '
            'Declare the field in `parameters` or fix the script.'
        )

    def validate_input(self, args: dict[str, Any]) -> dict[str, Any]:
        """The call's arguments as the plain data a plan reads as `input`; a Python type validates them."""
        if self._adapter is None:
            return args
        return to_jsonable_python(self._adapter.validate_python(args))


def _schema(adapter: TypeAdapter[Any]) -> JsonSchema:
    """The schema as Pydantic AI renders a tool's: the same generator, and no title on the object itself."""
    schema = adapter.json_schema(schema_generator=GenerateToolJsonSchema)
    schema.pop('title', None)
    return schema
