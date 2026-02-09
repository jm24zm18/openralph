from __future__ import annotations

import json
from pathlib import Path

from openralph.openralph_cli.loop.status import RunOutcome, write_run_artifacts


def test_write_run_artifacts(tmp_path: Path) -> None:
    status_path = tmp_path / ".ralph" / "RUN_STATUS.json"
    summary_path = tmp_path / ".ralph" / "RUN_SUMMARY.md"
    outcome = RunOutcome(
        status="partial",
        reason="feature_queue_incomplete",
        stage="feature_queue",
        completed_features=2,
        total_features=5,
        failed_features=1,
        done_marker=False,
        gate_pass=False,
        tool_errors=3,
        max_tool_errors=0,
    )
    write_run_artifacts(
        status_path,
        summary_path,
        outcome=outcome,
        prompt="Build game",
        auto_mode="full",
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert payload["reason"] == "feature_queue_incomplete"
    assert payload["auto_mode"] == "full"
    assert payload["prompt"] == "Build game"
    assert "timestamp_utc" in payload

    summary = summary_path.read_text(encoding="utf-8")
    assert "Status: partial" in summary
    assert "Features completed: 2/5" in summary
    assert "Tool errors: 3" in summary
