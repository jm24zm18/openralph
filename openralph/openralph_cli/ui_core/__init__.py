from __future__ import annotations

from .context import console, set_cli_ui_overrides
from .dashboard import Dashboard, DashboardState, run_summary
from .renderers import (
    config_table,
    doctor_table,
    feature_table,
    init_results_panel,
    memory_results,
    notice,
    proxy_panel,
    scaffold_created,
)


def _brief_tool_args(name: str, args: dict) -> str:
    if name == "bash":
        cmd = args.get("command", "")
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if name in ("edit_file", "write_file", "read_file"):
        path = args.get("path", args.get("file_path", ""))
        return str(path)[:60]
    if name in ("search", "repo_search", "search_repo"):
        return args.get("query", args.get("pattern", ""))[:60]
    for value in args.values():
        text = str(value)
        return text[:60] + ("..." if len(text) > 60 else "")
    return ""


__all__ = [
    "Dashboard",
    "DashboardState",
    "_brief_tool_args",
    "config_table",
    "console",
    "doctor_table",
    "feature_table",
    "init_results_panel",
    "memory_results",
    "notice",
    "proxy_panel",
    "run_summary",
    "scaffold_created",
    "set_cli_ui_overrides",
]
