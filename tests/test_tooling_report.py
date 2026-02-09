from __future__ import annotations

from pathlib import Path

from openralph.openralph_cli.tooling import doctor_report


def test_doctor_report_includes_runtime_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ralph").mkdir()

    statuses = doctor_report(
        repo=repo,
        ollama_host="http://127.0.0.1:9",
        embed_model="nomic-embed-text",
        proxy_enabled=False,
    )
    names = {s.name for s in statuses}
    assert "python-runtime" in names
    assert "node-runtime" in names
    assert "npm-runtime" in names


def test_doctor_proxy_enabled_not_running_is_not_fail(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ralph").mkdir()

    statuses = doctor_report(
        repo=repo,
        ollama_host="http://127.0.0.1:9",
        embed_model="nomic-embed-text",
        proxy_enabled=True,
        proxy_listen_port=18889,
    )
    proxy = next(s for s in statuses if s.name == "proxy")
    assert proxy.ok is True
    assert "enabled but not running" in proxy.detail
