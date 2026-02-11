from __future__ import annotations

from openralph.openralph_cli.planner import (
    FeatureQueueItem,
    _collect_semantic_plan_failures,
    _parse_planner_output,
)
from openralph.openralph_cli.planner_contracts import get_domain_contract
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
        log=_Log(),
        contract=get_domain_contract("game"),
    )
    assert failures
    assert any("under-scoped" in f for f in failures)


def test_semantic_plan_validation_accepts_engine_and_reset_naming() -> None:
    class _Log:
        def warning(self, *_args, **_kwargs) -> None:
            return None

    items = [
        FeatureQueueItem(
            slug="project-scaffold",
            title="Project Scaffold",
            status="pending",
            feature_path="docs/features/2026-02-09-project-scaffold",
        ),
        FeatureQueueItem(
            slug="core-game-engine",
            title="Core Game Engine",
            status="pending",
            feature_path="docs/features/2026-02-09-core-game-engine",
        ),
        FeatureQueueItem(
            slug="keyboard-controls",
            title="Keyboard Controls",
            status="pending",
            feature_path="docs/features/2026-02-09-keyboard-controls",
        ),
        FeatureQueueItem(
            slug="score-tracking",
            title="Score Tracking",
            status="pending",
            feature_path="docs/features/2026-02-09-score-tracking",
        ),
        FeatureQueueItem(
            slug="reset-button",
            title="Reset Button",
            status="pending",
            feature_path="docs/features/2026-02-09-reset-button",
        ),
    ]

    failures = _collect_semantic_plan_failures(
        items,
        log=_Log(),
        contract=get_domain_contract("game"),
    )
    assert failures == []
