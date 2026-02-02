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
        )
