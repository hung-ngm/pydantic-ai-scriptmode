"""ScriptMode: sandbox-free code mode for Pydantic AI. Scripts compile to an inert plan."""

from pydantic_ai_scriptmode._capability import ScriptMode
from pydantic_ai_scriptmode._compile import CompileError, compile_script
from pydantic_ai_scriptmode._execute import CallError, Dispatch, ExecuteResult, execute_plan
from pydantic_ai_scriptmode._plan import CallStep, DeriveStep, GuardStep, Limits, Plan, Step
from pydantic_ai_scriptmode._record import InMemoryRecordStore, Record, RecordStore, StepRecord
from pydantic_ai_scriptmode._teaching import Issue
from pydantic_ai_scriptmode._toolset import RUN_SCRIPT_TOOL_NAME, ScriptModeToolset
from pydantic_ai_scriptmode._validate import ToolSignature, ValidationError, validate_plan

__all__ = (
    'RUN_SCRIPT_TOOL_NAME',
    'CallError',
    'CallStep',
    'CompileError',
    'DeriveStep',
    'Dispatch',
    'ExecuteResult',
    'GuardStep',
    'InMemoryRecordStore',
    'Issue',
    'Limits',
    'Plan',
    'Record',
    'RecordStore',
    'ScriptMode',
    'ScriptModeToolset',
    'Step',
    'StepRecord',
    'ToolSignature',
    'ValidationError',
    'compile_script',
    'execute_plan',
    'validate_plan',
)
