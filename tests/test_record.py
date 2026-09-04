"""The record round-trips through a JSON object, so a store only moves that object (ADR 0006)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pydantic_ai_scriptmode._record import Record, StepRecord


class TestRecordRoundTrip:
    def test_a_suspended_fan_out_with_input_survives_json(self, parked_script_tool_record: Record):
        data = json.loads(json.dumps(parked_script_tool_record.to_dict()))
        assert Record.from_dict(data) == parked_script_tool_record

    def test_to_dict_is_json_safe_for_values_a_custom_dispatch_may_settle(self):
        when = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
        record = Record(steps={'when': StepRecord(hash='a1', status='done', value=(when, {1, 2}))})
        data = record.to_dict()
        assert json.loads(json.dumps(data)) == data
        assert Record.from_dict(data).steps['when'].value == ['2026-09-04T12:00:00Z', [1, 2]]

    def test_from_dict_refuses_a_key_it_does_not_know(self):
        data = Record().to_dict()
        data['revision'] = 3
        with pytest.raises(TypeError, match='revision'):
            Record.from_dict(data)
