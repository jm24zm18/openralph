from __future__ import annotations

from openralph.openralph_cli import loop


def test_parse_gate_pass() -> None:
    assert loop._parse_gate("Gate: PASS") is True
    assert loop._parse_gate("gate: pass") is True


def test_parse_gate_fail() -> None:
    assert loop._parse_gate("Gate: FAIL") is False
    assert loop._parse_gate("Gate: fail") is False


def test_parse_gate_missing() -> None:
    assert loop._parse_gate("No gate here") is None


def test_extract_json_from_response() -> None:
    payload = '{"project_name": "Ralph", "problem": "X"}'
    assert loop._extract_json_from_response(payload) == {
        "project_name": "Ralph",
        "problem": "X",
    }
    assert loop._extract_json_from_response("not json") is None
