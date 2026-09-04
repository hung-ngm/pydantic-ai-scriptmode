"""`ScriptTool`: a saved script under a name, compiled at construction."""

from __future__ import annotations

import pytest
from typing_extensions import NotRequired, TypedDict

from pydantic_ai_scriptmode import CompileError, ScriptTool
from pydantic_ai_scriptmode._script_tool import InputError

CLOSE_STALE = """
# Close every stale issue in a repository
issues = await list_issues(repo=input.repo)
stale = [i for i in issues if i.stale]
closed = [await close_issue(repo=input.repo, number=i.number) for i in stale[:20]]
return {'closed': len(closed)}
"""


class Params(TypedDict):
    repo: str
    limit: NotRequired[int]


class TestConstruction:
    def test_compiles_the_script_and_the_description_defaults_to_the_intent(self):
        tool = ScriptTool('close_stale', CLOSE_STALE, parameters=Params)
        assert tool.name == 'close_stale'
        assert tool.plan.intent == 'Close every stale issue in a repository'
        assert [s.name for s in tool.plan.steps] == ['issues', 'stale', 'closed']
        assert tool.description == 'Close every stale issue in a repository'
        assert ScriptTool(
            'close_stale', CLOSE_STALE, parameters=Params, description='Close stale issues'
        ).description == ('Close stale issues')

    def test_a_script_that_does_not_compile_fails_at_construction(self):
        with pytest.raises(CompileError) as exc_info:
            ScriptTool('bad', 'while True:\n    pass')
        assert exc_info.value.issues


class TestParameters:
    def test_a_python_type_renders_its_json_schema_and_validates_the_arguments(self):
        tool = ScriptTool('close_stale', CLOSE_STALE, parameters=Params, returns=dict[str, int])
        assert tool.parameters_json_schema == {
            'type': 'object',
            'properties': {'repo': {'type': 'string'}, 'limit': {'type': 'integer'}},
            'required': ['repo'],
        }
        assert tool.return_schema == {'type': 'object', 'additionalProperties': {'type': 'integer'}}
        assert tool.validate_input({'repo': 'api'}) == {'repo': 'api'}
        with pytest.raises(InputError, match='repo'):
            tool.validate_input({'repo': 3})

    def test_a_json_schema_passes_through_and_the_default_takes_no_arguments(self):
        schema = {'type': 'object', 'properties': {'repo': {'type': 'string'}}, 'required': ['repo']}
        tool = ScriptTool('close_stale', CLOSE_STALE, parameters=schema)
        assert tool.parameters_json_schema == schema
        assert tool.validate_input({'repo': 'api', 'extra': 1}) == {'repo': 'api', 'extra': 1}
        with pytest.raises(InputError, match='repo'):
            tool.validate_input({})
        with pytest.raises(InputError, match='object'):
            tool.validate_input([])  # pyright: ignore[reportArgumentType]
        bare = ScriptTool('list_all', '# List all\nissues = await list_issues(repo="api")')
        assert bare.parameters_json_schema == {'type': 'object', 'properties': {}}
        assert bare.return_schema is None
        assert bare.validate_input({}) == {}


class TestInputFields:
    def test_a_read_of_an_undeclared_field_fails_at_construction(self):
        script = CLOSE_STALE.replace('input.repo', 'input.repos', 1)
        with pytest.raises(ValueError, match=r'`close_stale` reads `input.repos`.*declared: limit, repo'):
            ScriptTool('close_stale', script, parameters=Params)
        with pytest.raises(ValueError, match=r'`input.repo`.*no parameters'):
            ScriptTool('close_stale', CLOSE_STALE)

    def test_subscript_reads_count_and_an_open_schema_accepts_any_field(self):
        script = CLOSE_STALE.replace('input.repo', "input['repo']")
        with pytest.raises(ValueError, match=r'`input.repo`'):
            ScriptTool('close_stale', script, parameters={'type': 'object', 'properties': {'name': {}}})
        ScriptTool('close_stale', script, parameters={'type': 'object', 'additionalProperties': True})
        ScriptTool('close_stale', script, parameters=dict[str, str])


class TestName:
    def test_the_name_must_be_callable_from_a_script_as_written(self):
        with pytest.raises(ValueError, match=r"'close-stale'.*identifier"):
            ScriptTool('close-stale', CLOSE_STALE, parameters=Params)

    def test_the_return_line_counts_and_dict_methods_are_not_fields(self):
        script = CLOSE_STALE.replace(
            "return {'closed': len(closed)}", "return {'closed': len(closed), 'repo': input.rpeo}"
        )
        with pytest.raises(ValueError, match=r'`input.rpeo`'):
            ScriptTool('close_stale', script, parameters=Params)
        ScriptTool(
            'close_stale',
            "# Get\nissues = await list_issues(repo=input.get('repo', 'api'), n=len(input.keys()) + len(input.items()))",
            parameters=Params,
        )
        with pytest.raises(ValueError, match=r'`input.rpeo`'):
            ScriptTool('close_stale', "# Get\nissues = await list_issues(repo=input.get('rpeo'))", parameters=Params)
