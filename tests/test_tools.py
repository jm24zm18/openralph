from __future__ import annotations

from pathlib import Path

import openralph.openralph_cli.agent.tools as tools_module
from openralph.openralph_cli.agent.tools import (
    ToolContext,
    _normalize_tool_args,
    _resolve_path,
    _resolve_tool_alias,
    _run_bash,
    _write_file_via_bash,
    execute_tool,
)


def test_run_bash_success(mock_tool_context) -> None:
    output, is_error = _run_bash("printf 'ok'", 5, mock_tool_context)
    assert is_error is False
    assert "ok" in output
    assert "[exit code: 0]" in output


def test_run_bash_failure_sets_error(mock_tool_context) -> None:
    output, is_error = _run_bash("bash -lc 'exit 3'", 5, mock_tool_context)
    assert is_error is True
    assert "[exit code: 3]" in output


def test_run_bash_timeout_sets_error(mock_tool_context) -> None:
    output, is_error = _run_bash("sleep 2", 1, mock_tool_context)
    assert is_error is True
    assert "[exit code: -1]" in output


def test_alias_quotes_mkdir_path() -> None:
    _, args = _resolve_tool_alias("mkdir", {"path": "dir with spaces"}) or ("", {})
    assert args["command"] == "mkdir -p 'dir with spaces'"


def test_alias_quotes_rm_path() -> None:
    _, args = _resolve_tool_alias("delete_file", {"path": "a b.txt"}) or ("", {})
    assert args["command"] == "rm -f 'a b.txt'"


def test_resolve_path_prevents_escape(mock_tool_context) -> None:
    try:
        _resolve_path("../outside.txt", mock_tool_context)
    except ValueError as e:
        assert "outside repository" in str(e)
        return
    raise AssertionError("Expected ValueError for path escape")


def test_write_file_via_bash_handles_spaces(mock_tool_context) -> None:
    output, is_error = _write_file_via_bash("nested dir/file name.txt", "hello", mock_tool_context)
    assert is_error is False
    assert "[exit code: 0]" in output
    path = Path(mock_tool_context.repo) / "nested dir" / "file name.txt"
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_execute_tool_respects_allowed_tools(tmp_repo: Path) -> None:
    ctx = ToolContext(repo=tmp_repo, allowed_tools={"read_file"})
    result, is_error = execute_tool("bash", {"command": "echo hi"}, ctx)
    assert is_error is True
    assert "not permitted" in result


def test_execute_tool_rejects_unknown_tool_name(tmp_repo: Path) -> None:
    ctx = ToolContext(repo=tmp_repo)
    result, is_error = execute_tool("totally_unknown_tool", {"path": "."}, ctx)
    assert is_error is True
    assert "Unknown tool: totally_unknown_tool" in result


def test_normalize_tool_args_collapses_json_suffix() -> None:
    name, args = _normalize_tool_args("list_dirjson", {"path": "."})
    assert name == "list_dir"
    assert args["path"] == "."


def test_execute_tool_aliases_print_tree_to_list_dir(tmp_repo: Path) -> None:
    ctx = ToolContext(repo=tmp_repo)
    result, is_error = execute_tool("print_tree", {"path": "."}, ctx)
    assert is_error is False
    assert result is not None


def test_execute_tool_aliases_navigate_to_browser_navigate(tmp_repo: Path) -> None:
    class StubSession:
        def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict:
            return {"url": url, "wait_until": wait_until}

    original = tools_module.get_session
    tools_module.get_session = lambda _cfg: StubSession()
    try:
        ctx = ToolContext(repo=tmp_repo)
        result, is_error = execute_tool("navigate", {"url": "https://example.com"}, ctx)
    finally:
        tools_module.get_session = original

    assert is_error is False
    assert "https://example.com" in result


def test_browser_console_tool_dispatch(tmp_repo: Path) -> None:
    class StubSession:
        def get_console(self, level=None, last_n=50, clear=False):  # noqa: ANN001
            return [{"type": level or "log", "text": "ok", "last_n": last_n, "clear": clear}]

    original = tools_module.get_session
    tools_module.get_session = lambda _cfg: StubSession()
    try:
        ctx = ToolContext(repo=tmp_repo)
        result, is_error = execute_tool("browser_console", {"level": "error", "last_n": 3}, ctx)
    finally:
        tools_module.get_session = original

    assert is_error is False
    assert "\"type\": \"error\"" in result
