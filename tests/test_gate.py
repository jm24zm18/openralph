from __future__ import annotations

from openralph.openralph_cli import loop


def test_parse_gate_markdown_heading() -> None:
    assert loop._parse_gate("## Gate: PASS") is True
    assert loop._parse_gate("# Gate: FAIL") is False


def test_parse_gate_ignores_missing() -> None:
    assert loop._parse_gate("Gate unknown") is None
