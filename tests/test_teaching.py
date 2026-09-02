from __future__ import annotations

from typing import get_args

import pytest

from pydantic_ai_scriptmode._teaching import TEACHING, RejectionKind, explain


class TestTeaching:
    def test_every_kind_has_a_table_entry(self):
        assert set(TEACHING) == set(get_args(RejectionKind))

    def test_fallback_rendering_names_the_kind_and_details(self):
        assert explain('while_loop') == 'while_loop' or TEACHING['while_loop']
        text = explain('unbounded_for', iter='xs')
        assert 'xs' in text

    def test_every_kind_has_copy(self):
        missing = [kind for kind, template in TEACHING.items() if not template]
        assert missing == []

    @pytest.mark.parametrize('kind', get_args(RejectionKind))
    def test_templates_render_with_their_documented_details(self, kind: RejectionKind):
        details = {
            'iter': 'xs',
            'name': 'x',
            'target': 'x',
            'node': 'Assert',
            'tool': 'fetch',
            'option': '_retry',
            'value': "'later'",
            'message': 'invalid syntax',
            'step': 's',
            'argument': 'a',
            'count': 3,
            'limit': 2,
        }
        assert explain(kind, **details)
