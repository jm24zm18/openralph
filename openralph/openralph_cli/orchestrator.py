from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
import json
import os
import subprocess

from .logging import get_logger
from .opencode_manager import ensure_opencode
from .paths import Paths
from .settings import OpenRalphSettings


@dataclass
class TaskItem:
    id: str
    type: str  # feature | bugfix | test | refactor
    title: str
    description: str
    priority: int
    status: str  # pending | in_progress | blocked | done
    assigned_to: str  # code | test | review
    blockers: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "assigned_to": self.assigned_to,
            "blockers": list(self.blockers),
        }


def _read_template(name: str, fallback: str) -> str:
    try:
        return resources.files("openralph.templates").joinpath(name).read_text(encoding="utf-8")
    except Exception:
        return fallback


def _read_text(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


def _read_recent_logs(paths: Paths, max_files: int = 3, max_chars: int = 8000) -> str:
    if not paths.logs.exists():
        return ""
    try:
        files = [p for p in paths.logs.glob("*.log") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    if not files:
        return ""
    chunks: list[str] = []
    for path in files[:max_files]:
        content = _read_text(path, max_chars=max_chars)
        if not content:
            continue
        chunks.append(f"# {path.name}\n\n{content}")
    return "\n\n".join(chunks)


def _extract_json_array(output: str) -> list[dict]:
    decoder = json.JSONDecoder()
    idx = 0
    last_valid: list[dict] | None = None
    while idx < len(output):
        start = output.find("[", idx)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(output, start)
            if isinstance(obj, list):
                last_valid = obj
            idx = end
        except Exception:
            idx = start + 1
    if last_valid is None:
        raise ValueError("No JSON array found in orchestrator output")
    return last_valid


def _coerce_task(raw: dict, idx: int) -> TaskItem:
    task_id = str(raw.get("id") or f"task-{idx}")
    title = str(raw.get("title") or f"Task {idx}")
    task_type = str(raw.get("type") or "feature")
    description = str(raw.get("description") or "")
    priority = int(raw.get("priority") or idx)
    status = str(raw.get("status") or "pending")
    assigned_to = str(raw.get("assigned_to") or "code")
    blockers_raw = raw.get("blockers") or []
    if isinstance(blockers_raw, str):
        blockers = [blockers_raw]
    elif isinstance(blockers_raw, list):
        blockers = [str(b) for b in blockers_raw]
    else:
        blockers = []
    return TaskItem(
        id=task_id,
        type=task_type,
        title=title,
        description=description,
        priority=priority,
        status=status,
        assigned_to=assigned_to,
        blockers=blockers,
    )

def _default_prd_task() -> TaskItem:
    return TaskItem(
        id="task-1",
        type="feature",
        title="Implement PRD",
        description="Implement the current docs/PRD.md requirements.",
        priority=1,
        status="pending",
        assigned_to="code",
        blockers=[],
    )


def _merge_task_status(existing: dict[str, TaskItem], planned: list[TaskItem]) -> list[TaskItem]:
    merged: list[TaskItem] = []
    for task in planned:
        prev = existing.get(task.id)
        if prev is not None:
            task.status = prev.status
            if prev.blockers and not task.blockers:
                task.blockers = list(prev.blockers)
        merged.append(task)
    return merged


def _load_task_status(paths: Paths) -> list[TaskItem]:
    if not paths.task_status.exists():
        return []
    try:
        data = json.loads(paths.task_status.read_text(encoding="utf-8"))
        items = data.get("tasks", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        tasks: list[TaskItem] = []
        for idx, raw in enumerate(items, start=1):
            if isinstance(raw, dict):
                tasks.append(_coerce_task(raw, idx))
        return tasks
    except Exception:
        return []


def load_task_status(repo: Path) -> list[TaskItem]:
    paths = Paths.for_repo(repo)
    return _load_task_status(paths)


def write_task_status(paths: Paths, tasks: list[TaskItem]) -> None:
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tasks": [t.to_dict() for t in tasks],
    }
    paths.task_status.parent.mkdir(parents=True, exist_ok=True)
    paths.task_status.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_feature_plan(paths: Paths, tasks: list[TaskItem]) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = ["# Feature Plan", f"Generated: {ts}", ""]
    if not tasks:
        lines.append("No planned tasks.")
    else:
        tasks_sorted = sorted(tasks, key=lambda t: (t.priority, t.id))
        for task in tasks_sorted:
            lines.append(f"## Priority {task.priority}: {task.title}")
            lines.append(f"- **Type:** {task.type}")
            lines.append(f"- **Status:** {task.status}")
            lines.append(f"- **Assigned:** {task.assigned_to}")
            if task.blockers:
                blockers = ", ".join(task.blockers)
                lines.append(f"- **Blockers:** {blockers}")
            lines.append(f"- **Description:** {task.description}")
            lines.append("")
    paths.feature_plan.parent.mkdir(parents=True, exist_ok=True)
    paths.feature_plan.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _run_opencode(repo: Path, oc_path: Path, prompt: str, env: dict[str, str]) -> str:
    result = subprocess.run([str(oc_path), "run", prompt], cwd=str(repo), env=env, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or f"OpenCode failed (rc={result.returncode})")
    return result.stdout or ""

def _render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, val in values.items():
        rendered = rendered.replace("{" + key + "}", val)
    return rendered


def run_orchestrator(repo: Path, settings: OpenRalphSettings, *, oc_path: Path | None = None) -> list[TaskItem]:
    log = get_logger("orchestrator")
    repo = repo.resolve()
    paths = Paths.for_repo(repo)
    oc = oc_path or ensure_opencode(repo, auto_install=settings.opencode_auto_install, version=settings.opencode_version).path

    prd_content = _read_text(paths.prd, max_chars=12000)
    test_report = _read_text(paths.test_report, max_chars=8000)
    recent_logs = _read_recent_logs(paths, max_files=3, max_chars=8000)
    current_plan = _read_text(paths.feature_plan, max_chars=8000)

    template = _read_template(
        "orchestrator-prompt.md",
        (
            "You are the Feature Orchestrator Agent.\n\n"
            "PRD: {prd_content}\n\n"
            "Recent Test Report: {test_report}\n\n"
            "Recent Logs: {log_summary}\n\n"
            "Current Feature Plan: {current_plan}\n\n"
            "Output a JSON array of tasks.\n"
        ),
    )

    prompt = _render_template(
        template,
        {
            "prd_content": prd_content or "(none)",
            "test_report": test_report or "(none)",
            "log_summary": recent_logs or "(none)",
            "current_plan": current_plan or "(none)",
        },
    )

    env = os.environ.copy()
    env.setdefault("OPENCODE_HOME", str(repo / ".opencode"))

    existing = {t.id: t for t in _load_task_status(paths)}
    try:
        output = _run_opencode(repo, oc, prompt, env)
        raw_tasks = _extract_json_array(output)
        planned = [_coerce_task(raw, idx) for idx, raw in enumerate(raw_tasks, start=1)]
        if settings.orchestrator_max_tasks > 0:
            planned = planned[: settings.orchestrator_max_tasks]
        merged = _merge_task_status(existing, planned)
        write_task_status(paths, merged)
        write_feature_plan(paths, merged)
        return merged
    except Exception as e:
        log.warning("Orchestrator failed; falling back to existing plan: %s", e)
        existing_tasks = list(existing.values())
        if not existing_tasks and paths.prd.exists():
            existing_tasks = [_default_prd_task()]
        if existing_tasks:
            write_task_status(paths, existing_tasks)
            write_feature_plan(paths, existing_tasks)
        return existing_tasks


def _is_blocked(task: TaskItem, tasks_by_id: dict[str, TaskItem]) -> bool:
    if not task.blockers:
        return False
    for blocker_id in task.blockers:
        blocker = tasks_by_id.get(blocker_id)
        if blocker is not None and blocker.status != "done":
            return True
    return False


def select_next_task(tasks: list[TaskItem]) -> TaskItem | None:
    if not tasks:
        return None
    tasks_by_id = {t.id: t for t in tasks}
    in_progress = [t for t in tasks if t.status == "in_progress" and not _is_blocked(t, tasks_by_id)]
    if in_progress:
        return sorted(in_progress, key=lambda t: (t.priority, t.id))[0]
    pending = [t for t in tasks if t.status == "pending" and not _is_blocked(t, tasks_by_id)]
    if not pending:
        return None
    return sorted(pending, key=lambda t: (t.priority, t.id))[0]


def build_task_prompt(task: TaskItem, feature_ctx: str | None) -> str:
    lines = [
        "You are the Builder Agent.",
        "",
        "Implement the following task:",
        f"Task ID: {task.id}",
        f"Title: {task.title}",
        f"Type: {task.type}",
        f"Priority: {task.priority}",
        f"Assigned: {task.assigned_to}",
        f"Description: {task.description}",
    ]
    if feature_ctx:
        lines.append("")
        lines.append("Current feature context:")
        lines.append(feature_ctx)
    return "\n".join(lines)


def run_orchestrator_iteration(
    repo: Path,
    settings: OpenRalphSettings,
    *,
    oc_path: Path | None = None,
    iteration: int = 1,
) -> TaskItem | None:
    paths = Paths.for_repo(repo)
    if not settings.orchestrator_enabled:
        return None

    do_replan = not paths.task_status.exists()
    if settings.orchestrator_replan_every > 0 and iteration % settings.orchestrator_replan_every == 0:
        do_replan = True

    tasks = run_orchestrator(repo, settings, oc_path=oc_path) if do_replan else _load_task_status(paths)
    if not tasks and not do_replan:
        tasks = run_orchestrator(repo, settings, oc_path=oc_path)
    if not tasks:
        return None

    current = select_next_task(tasks)
    if current is None:
        return None

    if current.status != "in_progress":
        current.status = "in_progress"
        write_task_status(paths, tasks)
        write_feature_plan(paths, tasks)
    return current


def mark_task_status(repo: Path, task_id: str, status: str) -> None:
    paths = Paths.for_repo(repo)
    tasks = _load_task_status(paths)
    if not tasks:
        return
    updated = False
    for task in tasks:
        if task.id == task_id:
            task.status = status
            updated = True
            break
    if updated:
        write_task_status(paths, tasks)
        write_feature_plan(paths, tasks)


def format_task_brief(task: TaskItem) -> str:
    blockers = ", ".join(task.blockers) if task.blockers else "None"
    return (
        f"{task.id} | P{task.priority} | {task.type} | {task.status}\n"
        f"Title: {task.title}\n"
        f"Assigned: {task.assigned_to}\n"
        f"Blockers: {blockers}\n"
        f"Description: {task.description}"
    )
