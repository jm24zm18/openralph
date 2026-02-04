from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def test_doctor_ok(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def _fake_find_opencode(_path: Path):
        return SimpleNamespace(path=repo / "opencode", source="test")

    def _fake_doctor_report(**_kwargs):
        return [SimpleNamespace(ok=True, name="memory", detail="ok", hint="")]

    monkeypatch.setattr("openralph.openralph_cli.cli.find_opencode", _fake_find_opencode)
    monkeypatch.setattr("openralph.openralph_cli.cli.opencode_version", lambda _p: "0.0.0")
    monkeypatch.setattr("openralph.openralph_cli.cli.doctor_report", _fake_doctor_report)
    monkeypatch.setattr("openralph.openralph_cli.cli.managed_block_is_current", lambda *_a, **_k: True)

    result = runner.invoke(app, ["doctor", str(repo)])
    assert result.exit_code == 0
    assert "All checks passed." in result.stdout


def test_run_command(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr("openralph.openralph_cli.cli.run_loop", lambda *_a, **_k: False)
    monkeypatch.setattr("openralph.openralph_cli.cli.get_log_file", lambda: None)

    result = runner.invoke(app, ["run", str(repo), "Do work", "--max-iters", "1"])
    assert result.exit_code == 0
    assert "Done" in result.stdout


def test_memory_commands(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr("openralph.openralph_cli.cli.init_db", lambda *_a, **_k: None)
    monkeypatch.setattr("openralph.openralph_cli.cli.index_repo", lambda *_a, **_k: None)
    monkeypatch.setattr("openralph.openralph_cli.cli.vacuum_db", lambda *_a, **_k: None)

    hit = SimpleNamespace(path="docs/PRD.md", chunk_index=0, score=0.9, content="content")
    monkeypatch.setattr("openralph.openralph_cli.cli.query_memory", lambda *_a, **_k: [hit])

    result = runner.invoke(app, ["memory", "index", str(repo)])
    assert result.exit_code == 0

    result = runner.invoke(app, ["memory", "query", str(repo), "query"])
    assert result.exit_code == 0
    assert "docs/PRD.md" in result.stdout

    result = runner.invoke(app, ["memory", "vacuum", str(repo)])
    assert result.exit_code == 0


def test_init_command(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    settings = SimpleNamespace(
        log_level="INFO",
        init_node_tooling="local",
        init_create_venv=False,
        init_with_opencode_json=False,
        init_write_skills=False,
        init_force_skills=False,
        init_force_opencode_json=False,
        init_install_tools=False,
        init_playwright=False,
        init_playwright_browsers=False,
        proxy_enabled=False,
        proxy_listen_port=18889,
        proxy_target_host="127.0.0.1",
        proxy_target_port=30000,
        proxy_target_model="model",
        proxy_provider_name="provider",
        proxy_provider_display="display",
        proxy_model_id="model",
        proxy_model_display="display",
        proxy_api_key="key",
        agents_enabled=False,
        agents_default_provider="",
        agents_default_model="",
        agent_code_model="",
        agent_code_permissions=[],
        agent_plan_model="",
        agent_plan_permissions=[],
        agent_test_model="",
        agent_test_permissions=[],
        agent_review_model="",
        agent_review_permissions=[],
        loop_test_report=".ralph/TEST_REPORT.md",
        loop_review_report=".ralph/REVIEW_REPORT.md",
        loop_final_report=".ralph/FINAL.md",
        opencode_auto_install=False,
        opencode_version="",
    )

    monkeypatch.setattr("openralph.openralph_cli.cli.OpenRalphSettings.load", lambda _p: settings)
    monkeypatch.setattr("openralph.openralph_cli.cli.ensure_opencode", lambda *_a, **_k: SimpleNamespace(path=repo / "opencode", source="test"))
    monkeypatch.setattr("openralph.openralph_cli.cli.ensure_tools", lambda *_a, **_k: [])
    monkeypatch.setattr("openralph.openralph_cli.cli.write_opencode_json", lambda *_a, **_k: repo / "opencode.json")
    monkeypatch.setattr("openralph.openralph_cli.cli.write_default_skills", lambda *_a, **_k: None)

    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0
