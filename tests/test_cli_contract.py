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


def test_run_writes_failed_artifacts_if_run_loop_raises(monkeypatch, tmp_path) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("openralph.openralph_cli.cli.run_loop", _boom)

    result = runner.invoke(app, ["run", str(tmp_path), "test prompt"])
    assert result.exit_code == 1

    status_path = tmp_path / ".ralph" / "RUN_STATUS.json"
    summary_path = tmp_path / ".ralph" / "RUN_SUMMARY.md"
    assert status_path.exists()
    assert summary_path.exists()
    assert "run_loop_crashed: boom" in status_path.read_text(encoding="utf-8")
