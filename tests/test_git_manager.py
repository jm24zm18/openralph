from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openralph.openralph_cli.git_manager import (
    checkpoint_commit,
    ensure_branch,
    head_sha,
    is_git_repo,
    rollback_to_checkpoint,
)


def test_is_git_repo(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()

    assert is_git_repo(repo) is False

    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
    assert is_git_repo(repo) is True


def test_branch_checkpoint_and_rollback(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo), check=True)

    (repo / "file.txt").write_text("v1", encoding="utf-8")
    sha1 = checkpoint_commit(repo, "checkpoint 1")
    assert sha1

    branch = ensure_branch(repo, "test-branch")
    assert branch == "openralph/test-branch"

    (repo / "file.txt").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=str(repo), check=True, capture_output=True, text=True)
    sha2 = head_sha(repo)
    assert sha2 != sha1

    rolled = rollback_to_checkpoint(repo)
    assert rolled == sha1
    assert head_sha(repo) == sha1
