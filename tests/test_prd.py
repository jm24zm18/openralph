from __future__ import annotations

from pathlib import Path

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
