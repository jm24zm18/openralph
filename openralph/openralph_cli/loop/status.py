from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass
class RunOutcome:
    status: str  # success | success_with_warnings | partial | blocked | failed
    reason: str = ""
    stage: str = ""
    completed_features: int = 0
    total_features: int = 0
    failed_features: int = 0
    done_marker: bool = False
    gate_pass: bool = False
    tool_errors: int = 0
    max_tool_errors: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"success", "success_with_warnings"}


def write_run_artifacts(
    status_path: Path,
    summary_path: Path,
    *,
    outcome: RunOutcome,
    prompt: str,
    auto_mode: str,
) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(outcome)
    payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    payload["auto_mode"] = auto_mode or "off"
    payload["prompt"] = prompt
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Run Summary",
        "",
        f"- Status: {outcome.status}",
        f"- Reason: {outcome.reason or '(none)'}",
        f"- Stage: {outcome.stage or '(unknown)'}",
        f"- Auto mode: {auto_mode or 'off'}",
        f"- Features completed: {outcome.completed_features}/{outcome.total_features}",
        f"- Features failed: {outcome.failed_features}",
        f"- DONE marker: {'yes' if outcome.done_marker else 'no'}",
        f"- Gate PASS: {'yes' if outcome.gate_pass else 'no'}",
        f"- Tool errors: {outcome.tool_errors}",
        f"- Max tool errors: {outcome.max_tool_errors}",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
