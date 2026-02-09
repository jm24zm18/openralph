from __future__ import annotations

import json
from pathlib import Path

from openralph.openralph_cli.loop.orchestrator import run_loop
from openralph.openralph_cli.settings import OpenRalphSettings


def test_blocked_preflight_still_writes_run_artifacts(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = OpenRalphSettings.load(repo)

    monkeypatch.setattr(
        "openralph.openralph_cli.loop.orchestrator._ensure_proxy",
        lambda settings, log: None,
    )
    monkeypatch.setattr(
        "openralph.openralph_cli.loop.orchestrator._preflight_backend",
        lambda settings: (False, "127.0.0.1:18889 unreachable (connection refused)"),
    )

    outcome = run_loop(repo, "test prompt", max_iters=1, settings=settings, mode="standard")
    assert outcome.status == "blocked"
    assert "backend_unreachable" in outcome.reason

    status_path = repo / ".ralph" / "RUN_STATUS.json"
    summary_path = repo / ".ralph" / "RUN_SUMMARY.md"
    assert status_path.exists()
    assert summary_path.exists()

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["stage"] == "preflight"


def test_success_downgraded_to_warning_when_tool_errors_exceed_threshold(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = OpenRalphSettings.load(repo)
    settings.loop_max_tool_errors = 0
    settings.ui_dashboard = True
    (repo / "docs").mkdir()
    (repo / "docs" / "PRD.md").write_text("# PRD\n", encoding="utf-8")

    class _FakeDashboard:
        def __init__(self) -> None:
            self.state = type("State", (), {"tool_errors": 2, "gate_history": []})()

        def start(self) -> None:
            return

        def stop(self) -> None:
            return

    def _fake_run_feature_iterations(**kwargs):
        paths = kwargs["paths"]
        paths.done_marker.write_text("auto\n", encoding="utf-8")
        paths.test_report.write_text("Gate: PASS\n", encoding="utf-8")
        return True

    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator._ensure_proxy", lambda settings, log: None)
    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator._preflight_backend", lambda settings: (True, "ok"))
    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator._reindex", lambda *args, **kwargs: None)
    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator._ensure_stack_choice", lambda *args, **kwargs: "python")
    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator._run_feature_iterations", _fake_run_feature_iterations)
    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator.Dashboard", _FakeDashboard)
    monkeypatch.setattr("openralph.openralph_cli.loop.orchestrator.run_summary", lambda state: None)

    outcome = run_loop(repo, "test prompt", max_iters=1, settings=settings, mode="standard")
    assert outcome.status == "success_with_warnings"
    assert "tool_errors_exceeded_threshold" in outcome.reason

    status_payload = json.loads((repo / ".ralph" / "RUN_STATUS.json").read_text(encoding="utf-8"))
    assert status_payload["status"] == "success_with_warnings"
    assert status_payload["tool_errors"] == 2
