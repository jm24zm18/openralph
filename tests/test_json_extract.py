from __future__ import annotations

from openralph.openralph_cli.json_extract import extract_json_array, extract_json_object


def test_extract_json_object_plain() -> None:
    data = extract_json_object('{"a": "b"}')
    assert data == {"a": "b"}


def test_extract_json_object_fenced() -> None:
    text = "output\n```json\n{\"a\": 1}\n```\n"
    data = extract_json_object(text)
    assert data == {"a": 1}


def test_extract_json_array_embedded() -> None:
    text = "notes before\n[1, 2, 3]\nnotes after"
    data = extract_json_array(text)
    assert data == [1, 2, 3]


def test_extract_json_returns_none_on_malformed() -> None:
    assert extract_json_object("{bad") is None
    assert extract_json_array("[bad") is None


def test_extract_json_returns_none_on_empty() -> None:
    assert extract_json_object("") is None
    assert extract_json_array("") is None
