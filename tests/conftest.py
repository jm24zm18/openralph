from __future__ import annotations

from pathlib import Path

import pytest

from openralph.openralph_cli.agent.tools import ToolContext


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


@pytest.fixture
def mock_tool_context(tmp_repo: Path) -> ToolContext:
    return ToolContext(repo=tmp_repo, sandbox_enabled=False, sandbox_mode="local")
