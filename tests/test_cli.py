from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from openralph.openralph_cli.cli import app


runner = CliRunner()


def test_config_show(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()

    result = runner.invoke(app, ["config", "show", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "Effective merged config" in result.stdout


def test_config_init_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()

    result = runner.invoke(app, ["config", "init", "--repo", str(repo), "--scope", "repo"])
    assert result.exit_code == 0
    assert (repo / ".openralph.toml").exists()
