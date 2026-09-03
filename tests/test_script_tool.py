"""`ScriptTool`: a saved script under a name, compiled at construction."""

from __future__ import annotations

import pytest

from pydantic_ai_scriptmode import CompileError, ScriptTool

CLOSE_STALE = """
# Close every stale issue in a repository
issues = await list_issues(repo=input.repo)
stale = [i for i in issues if i.stale]
closed = [await close_issue(repo=input.repo, number=i.number) for i in stale[:20]]
return {'closed': len(closed)}
"""


class TestConstruction:
    def test_compiles_the_script_and_the_description_defaults_to_the_intent(self):
        tool = ScriptTool('close_stale', CLOSE_STALE)
        assert tool.name == 'close_stale'
        assert tool.plan.intent == 'Close every stale issue in a repository'
        assert [s.name for s in tool.plan.steps] == ['issues', 'stale', 'closed']
        assert tool.description == 'Close every stale issue in a repository'
        assert ScriptTool('close_stale', CLOSE_STALE, description='Close stale issues').description == (
            'Close stale issues'
        )

    def test_a_script_that_does_not_compile_fails_at_construction(self):
        with pytest.raises(CompileError) as exc_info:
            ScriptTool('bad', 'while True:\n    pass')
        assert exc_info.value.issues
