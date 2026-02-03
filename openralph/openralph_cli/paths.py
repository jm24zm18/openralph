from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Paths:
    repo: Path
    ralph: Path
    memory_db: Path
    logs: Path
    proxy_pid: Path
    proxy_log: Path
    # PRD
    prd: Path
    prd_answers: Path
    # Orchestrator
    feature_plan: Path
    task_status: Path
    # Coordination files
    human_request: Path
    human_response: Path
    test_report: Path
    review_report: Path
    worklist: Path
    final_report: Path
    done_marker: Path
    last_green: Path

    @staticmethod
    def for_repo(repo: Path) -> "Paths":
        repo = repo.resolve()
        ralph = repo / ".ralph"
        logs = ralph / "logs"
        return Paths(
            repo=repo,
            ralph=ralph,
            memory_db=ralph / "memory.sqlite3",
            logs=logs,
            proxy_pid=ralph / "proxy.pid",
            proxy_log=logs / "proxy.log",
            # PRD
            prd=repo / "docs" / "PRD.md",
            prd_answers=ralph / "prd-answers.json",
            # Orchestrator
            feature_plan=ralph / "FEATURE_PLAN.md",
            task_status=ralph / "TASK_STATUS.json",
            # Coordination files
            human_request=ralph / "HUMAN_REQUEST.md",
            human_response=ralph / "HUMAN_RESPONSE.md",
            test_report=ralph / "TEST_REPORT.md",
            review_report=ralph / "REVIEW_REPORT.md",
            worklist=ralph / "WORKLIST.md",
            final_report=ralph / "FINAL.md",
            done_marker=ralph / "DONE",
            last_green=ralph / "LAST_GREEN.sha",
        )
