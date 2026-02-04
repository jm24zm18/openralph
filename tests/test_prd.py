from __future__ import annotations

from pathlib import Path

import json

from openralph.openralph_cli import prd


def test_repo_browser_glob(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hi')", encoding="utf-8")

    result = prd._repo_browser_glob(repo, {"path": "", "pattern": "src/*.py"})
    assert "src/app.py" in result


def test_repo_browser_tool_glob(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "PRD.md").write_text("PRD", encoding="utf-8")

    result = prd._execute_repo_browser_tool(repo, "glob", {"path": "", "pattern": "docs/*.md"})
    assert "docs/PRD.md" in result


def test_extract_json_from_output() -> None:
    keys = [k for k, _ in prd.PRD_QA_QUESTIONS]
    payload = {k: "x" for k in keys}
    output = f"noise\\n{json.dumps(payload)}\\ntrailing"
    assert prd._extract_json_from_output(output) == payload


def test_extract_json_from_output_uses_last_valid() -> None:
    keys = [k for k, _ in prd.PRD_QA_QUESTIONS]
    payload1 = {k: "a" for k in keys}
    payload2 = {k: "b" for k in keys}
    output = f"{json.dumps(payload1)}\\ntext\\n{json.dumps(payload2)}"
    assert prd._extract_json_from_output(output) == payload2


def test_collect_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("Hello", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "ignored.txt").write_text("nope", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hi')", encoding="utf-8")

    ctx = prd._collect_context(repo)
    assert ctx.repo_name == "repo"
    assert "README" in ctx.files
    assert any("src/app.py" == p for p in ctx.file_tree)
    assert all(".git" not in p for p in ctx.file_tree)
