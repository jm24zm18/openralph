from __future__ import annotations

from openralph.openralph_cli.planner import (
    FeatureQueueItem,
    _collect_semantic_plan_failures,
    _parse_planner_output,
)
from openralph.openralph_cli.settings import OpenRalphSettings


def test_parse_planner_output_valid_json_array() -> None:
    settings = OpenRalphSettings()
    output = '[{"slug":"feat-a","title":"A","path":"docs/features/2026-01-01-a"}]'
    items = _parse_planner_output(output, settings)
    assert len(items) == 1
    assert items[0].slug == "feat-a"


def test_parse_planner_output_embedded_fenced_json() -> None:
    settings = OpenRalphSettings()
    output = "text\n```json\n[{\"slug\":\"feat-a\",\"title\":\"A\",\"path\":\"docs/features/2026-01-01-a\"}]\n```\n"
    items = _parse_planner_output(output, settings)
    assert len(items) == 1


def test_parse_planner_output_invalid_returns_empty() -> None:
    settings = OpenRalphSettings()
    items = _parse_planner_output("not-json", settings)
    assert items == []


def test_semantic_plan_validation_for_playable_game_detects_under_scoped_plan() -> None:
    class _Log:
        def warning(self, *_args, **_kwargs) -> None:
            return None

    items = [
        FeatureQueueItem(
            slug="analytics-tracking",
            title="Analytics Tracking",
            status="pending",
            feature_path="docs/features/2026-02-09-analytics-tracking",
        )
    ]
    failures = _collect_semantic_plan_failures(
        items,
        "Build a playable browser game with controls and score.",
        log=_Log(),
    )
    assert failures
    assert any("under-scoped" in f for f in failures)
