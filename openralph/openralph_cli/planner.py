from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .paths import Paths
from .settings import OpenRalphSettings
from .prompts import PLANNER_SYSTEM, build_planner_prompt


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
    except Exception:
        return None


def save_feature_queue(paths: Paths, queue: FeatureQueue) -> None:
    queue_path = paths.feature_queue
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "created_from_prd": queue.created_from_prd,
        "items": [asdict(it) for it in queue.items],
    }
    queue_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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


def _validate_feature_files(repo: Path, items: list[FeatureQueueItem], log) -> None:
    required = ["00-brief.md", "01-requirements.md", "03-test-plan.md"]
    for item in items:
        folder = repo / item.feature_path
        if not folder.exists():
            log.warning("Feature folder missing: %s", item.feature_path)
            continue
        for fname in required:
            if not (folder / fname).exists():
                log.warning("Feature [%s] missing required file: %s", item.slug, fname)


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

    base_url = f"http://127.0.0.1:{settings.proxy_listen_port}"
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=settings.proxy_api_key,
        model=settings.proxy_model_id,
        timeout=settings.agent_timeout,
    )

    log_file = paths.logs / "planner.log"
    log.info("Running planner agent to decompose PRD into features")

    result = run_agent(
        provider=provider,
        prompt=prompt,
        repo=repo,
        config=AgentConfig(
            max_turns=settings.agent_max_turns,
            system_prompt=PLANNER_SYSTEM,
            timeout_default=settings.agent_timeout,
            max_output_chars=settings.agent_max_output,
        ),
    )

    output = result.final_text or ""
    log_content = (
        f"Prompt:\n{prompt[:3000]}\n\n---\n\nOutput:\n{output}\n\n---\n\n"
        f"Tool calls: {result.tool_calls_made}\nCompleted: {result.completed}\n"
    )
    if result.error:
        log_content += f"Error: {result.error}\n"
    log_file.write_text(log_content, encoding="utf-8")

    # Parse JSON summary from agent output
    items = _parse_planner_output(output, settings)
    _validate_feature_files(repo, items, log)
    prd_hash = _prd_hash(prd_text) if prd_text else ""

    queue = FeatureQueue(items=items, created_from_prd=prd_hash)
    save_feature_queue(paths, queue)

    log.info("Planner created %d features", len(items))
    return queue


def _parse_planner_output(output: str, settings: OpenRalphSettings) -> list[FeatureQueueItem]:
    """Extract the JSON feature list from planner agent output."""
    # Find the last JSON array in the output
    items: list[FeatureQueueItem] = []

    # Try to find a JSON array
    start = output.rfind("[")
    end = output.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return items

    try:
        data = json.loads(output[start:end + 1])
    except json.JSONDecodeError:
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
        if slug and path:
            items.append(FeatureQueueItem(
                slug=slug,
                title=title,
                status="pending",
                feature_path=path,
                iterations_used=0,
                max_iterations=max_iters,
            ))

    return items
