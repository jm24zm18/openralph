from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openralph.openralph_cli.git_manager import is_git_repo


def test_is_git_repo(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()

    assert is_git_repo(repo) is False

    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
    assert is_git_repo(repo) is True
