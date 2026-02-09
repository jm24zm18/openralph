from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .paths import Paths
from .settings import OpenRalphSettings, get_provider_config
from .prompts import PLANNER_SYSTEM, build_planner_prompt
from .json_extract import extract_json_array


@dataclass
class FeatureQueueItem:
    slug: str
    title: str
    status: str  # "pending" | "in_progress" | "done" | "failed"
    feature_path: str  # relative path, e.g. "docs/features/2026-02-05-game-loop"
    iterations_used: int = 0
    max_iterations: int = 5


@dataclass
class FeatureQueue:
    items: list[FeatureQueueItem] = field(default_factory=list)
    created_from_prd: str = ""  # sha256 hex of PRD content when queue was generated


def _prd_hash(prd_text: str) -> str:
    return hashlib.sha256(prd_text.encode("utf-8")).hexdigest()[:16]


def load_feature_queue(paths: Paths) -> FeatureQueue | None:
    queue_path = paths.feature_queue
    if not queue_path.exists():
        return None
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        items = [
            FeatureQueueItem(
                slug=it["slug"],
                title=it["title"],
                status=it["status"],
                feature_path=it["feature_path"],
                iterations_used=it.get("iterations_used", 0),
                max_iterations=it.get("max_iterations", 5),
            )
            for it in data.get("items", [])
        ]
        return FeatureQueue(items=items, created_from_prd=data.get("created_from_prd", ""))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_feature_queue(paths: Paths, queue: FeatureQueue) -> None:
    queue_path = paths.feature_queue
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "created_from_prd": queue.created_from_prd,
        "items": [asdict(it) for it in queue.items],
    }
    tmp_path = queue_path.with_suffix(queue_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(queue_path)


def next_pending_feature(queue: FeatureQueue) -> FeatureQueueItem | None:
    for item in queue.items:
        if item.status in ("pending", "in_progress"):
            return item
    return None


def mark_feature_status(queue: FeatureQueue, slug: str, status: str) -> None:
    for item in queue.items:
        if item.slug == slug:
            item.status = status
            return


def prd_changed(paths: Paths, queue: FeatureQueue) -> bool:
    prd_path = paths.prd
    if not prd_path.exists():
        return True
    current = _prd_hash(prd_path.read_text(encoding="utf-8"))
    return current != queue.created_from_prd


def _collect_missing_feature_files(repo: Path, items: list[FeatureQueueItem], log) -> list[str]:
    required = ["00-brief.md", "01-requirements.md", "03-test-plan.md"]
    missing: list[str] = []
    for item in items:
        if not item.feature_path.startswith("docs/features/"):
            log.warning("Feature [%s] has invalid path outside docs/features: %s", item.slug, item.feature_path)
            missing.append(f"{item.slug}:invalid-path")
            continue
        folder = repo / item.feature_path
        if not folder.exists():
            log.warning("Feature folder missing: %s", item.feature_path)
            missing.append(f"{item.slug}:<folder>")
            continue
        for fname in required:
            fpath = folder / fname
            if not fpath.exists():
                log.warning("Feature [%s] missing required file: %s", item.slug, fname)
                missing.append(f"{item.slug}:{fname}")
                continue
            content = fpath.read_text(encoding="utf-8", errors="ignore").strip()
            if len(content) < 40:
                log.warning("Feature [%s] has empty/too-short required file: %s", item.slug, fname)
                missing.append(f"{item.slug}:{fname}:too-short")
    return missing


def _collect_semantic_plan_failures(items: list[FeatureQueueItem], prd_text: str, log) -> list[str]:
    lower_prd = prd_text.lower()
    if not ("game" in lower_prd and ("playable" in lower_prd or "browser game" in lower_prd)):
        return []

    combined = " ".join(
        f"{it.slug} {it.title} {it.feature_path}".lower()
        for it in items
    )
    checks = {
        "setup/scaffold feature missing": ("setup", "scaffold", "project-setup", "bootstrap"),
        "gameplay loop feature missing": ("game-loop", "game loop", "loop", "gameplay"),
        "controls/input feature missing": ("controls", "input", "keyboard", "mouse"),
        "score feature missing": ("score", "points", "scoring"),
        "terminal/restart feature missing": ("game-over", "game over", "restart", "replay"),
    }
    failures: list[str] = []
    for label, tokens in checks.items():
        if not any(token in combined for token in tokens):
            log.warning("Planner semantic validation: %s", label)
            failures.append(label)

    # At least 4 core categories should exist for playable game plans.
    matched = len(checks) - len(failures)
    if matched < 4:
        failures.append("playable-game plan under-scoped (need >=4 core gameplay categories)")
    return failures


def generate_feature_queue(
    repo: Path,
    settings: OpenRalphSettings,
    paths: Paths,
    log,
) -> FeatureQueue:
    """Run the planner agent to decompose the PRD into features."""
    from .agent import run_agent, AgentConfig
    from .agent.providers import OpenAIProvider

    prd_text = paths.prd.read_text(encoding="utf-8") if paths.prd.exists() else ""
    existing = []
    if paths.features_dir.exists():
        for d in sorted(paths.features_dir.iterdir()):
            if d.is_dir():
                existing.append(d.name)

    prompt = build_planner_prompt(prd_text, existing)

    provider_cfg = get_provider_config(settings, role="plan")
    provider = OpenAIProvider(
        base_url=str(provider_cfg["base_url"]),
        api_key=str(provider_cfg["api_key"]),
        model=str(provider_cfg["model"]),
        timeout=int(provider_cfg["timeout"]),
    )

    log_file = paths.logs / "planner.log"
    log.info("Running planner agent to decompose PRD into features")

    def _run_planner_once(planner_prompt: str) -> tuple[list[FeatureQueueItem], str]:
        result = run_agent(
            provider=provider,
            prompt=planner_prompt,
            repo=repo,
            config=AgentConfig(
                max_turns=settings.agent_max_turns,
                system_prompt=PLANNER_SYSTEM,
                timeout_default=settings.agent_timeout,
                max_output_chars=settings.agent_max_output,
            ),
        )
        output = result.final_text or ""
        content = (
            f"Prompt:\n{planner_prompt[:3000]}\n\n---\n\nOutput:\n{output}\n\n---\n\n"
            f"Tool calls: {result.tool_calls_made}\nCompleted: {result.completed}\n"
        )
        if result.error:
            content += f"Error: {result.error}\n"
        return _parse_planner_output(output, settings), content

    items, log_content = _run_planner_once(prompt)
    missing = _collect_missing_feature_files(repo, items, log)
    semantic_failures = _collect_semantic_plan_failures(items, prd_text, log)

    if missing or semantic_failures:
        log.warning("Planner output failed validation; retrying once with strict repair prompt")
        repair_prompt = (
            prompt
            + "\n\nVALIDATION FAILURE:\n"
            + "- Every feature must include 00-brief.md, 01-requirements.md, and 03-test-plan.md.\n"
            + "- Missing files from previous attempt:\n"
            + ("".join(f"  - {m}\n" for m in missing) if missing else "  - (none)\n")
            + "- Semantic coverage gaps from previous attempt:\n"
            + ("".join(f"  - {m}\n" for m in semantic_failures) if semantic_failures else "  - (none)\n")
            + "- Ensure the plan covers core gameplay progression, not a single narrow feature.\n"
            + "- Fix all validation failures and return the final JSON summary again."
        )
        repaired_items, repaired_log = _run_planner_once(repair_prompt)
        log_content += "\n\n===== RETRY =====\n\n" + repaired_log
        repaired_missing = _collect_missing_feature_files(repo, repaired_items, log)
        repaired_semantic = _collect_semantic_plan_failures(repaired_items, prd_text, log)
        if repaired_missing or repaired_semantic:
            log_file.write_text(log_content, encoding="utf-8")
            issues = repaired_missing + repaired_semantic
            missing_text = ", ".join(issues[:12])
            raise RuntimeError(f"Planner output invalid after retry; validation failures: {missing_text}")
        items = repaired_items

    log_file.write_text(log_content, encoding="utf-8")
    prd_hash = _prd_hash(prd_text) if prd_text else ""

    queue = FeatureQueue(items=items, created_from_prd=prd_hash)
    save_feature_queue(paths, queue)

    log.info("Planner created %d features", len(items))
    return queue


def _parse_planner_output(output: str, settings: OpenRalphSettings) -> list[FeatureQueueItem]:
    """Extract the JSON feature list from planner agent output."""
    items: list[FeatureQueueItem] = []
    data = extract_json_array(output)
    if data is None:
        return items

    if not isinstance(data, list):
        return items

    max_iters = settings.loop_max_feature_iters

    for entry in data:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug", "")
        title = entry.get("title", slug)
        path = entry.get("path", "")
        if slug and path and isinstance(path, str) and path.startswith("docs/features/"):
            items.append(FeatureQueueItem(
                slug=slug,
                title=title,
                status="pending",
                feature_path=path,
                iterations_used=0,
                max_iterations=max_iters,
            ))

    return items
