from __future__ import annotations

from openralph.openralph_cli.proxy import _normalize_tool_name


def test_normalize_tool_name_handles_json_suffix() -> None:
    assert _normalize_tool_name("list_dirjson") == "list_dir"


def test_normalize_tool_name_handles_stacked_suffixes() -> None:
    assert _normalize_tool_name("globjsoncommentary") == "glob"

