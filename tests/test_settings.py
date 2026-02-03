from __future__ import annotations

from pathlib import Path

import pytest

from openralph.openralph_cli.settings import OpenRalphSettings, global_config_path, repo_config_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_repo_overrides_global(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()

    _write(global_config_path(), """[memory]\nk = 1\n""")
    _write(repo_config_path(repo), """[memory]\nk = 2\n""")

    settings = OpenRalphSettings.load(repo)
    assert settings.memory_k == 2


def test_env_override_ollama(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OLLAMA_HOST", "http://example.com")
    repo = tmp_path / "repo"
    repo.mkdir()

    settings = OpenRalphSettings.load(repo)
    assert settings.ollama_host == "http://example.com"


def test_invalid_chunk_overlap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo_config_path(repo), """[memory]\nchunk_chars = 100\nchunk_overlap = 100\n""")

    with pytest.raises(ValueError):
        OpenRalphSettings.load(repo)


def test_invalid_path_boost(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo_config_path(repo), """[memory]\npath_boosts = [[\"docs/PRD.md\", -1.0]]\n""")

    with pytest.raises(ValueError):
        OpenRalphSettings.load(repo)
