from __future__ import annotations

from typer.testing import CliRunner

from openralph.openralph_cli.cli import app


runner = CliRunner()


def test_config_show_accepts_positional_repo(tmp_path) -> None:
    result = runner.invoke(app, ["config", "show", str(tmp_path)])
    assert result.exit_code == 0


def test_config_show_accepts_repo_flag(tmp_path) -> None:
    result = runner.invoke(app, ["config", "show", "--repo", str(tmp_path)])
    assert result.exit_code == 0


def test_version_flag_available() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "openralph " in result.stdout


def test_config_show_invalid_config_returns_friendly_error(tmp_path) -> None:
    (tmp_path / ".openralph.toml").write_text('[proxy]\nlisten_port = "bad"\n', encoding="utf-8")
    result = runner.invoke(app, ["config", "show", str(tmp_path)])
    assert result.exit_code == 2
    assert "Invalid config" in result.stdout
    assert "proxy.listen_port" in result.stdout
