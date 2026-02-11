from __future__ import annotations

from openralph.openralph_cli.planner import FeatureQueueItem, _collect_semantic_plan_failures
from openralph.openralph_cli.planner_contracts import classify_domain, get_domain_contract


class _Log:
    def warning(self, *_args, **_kwargs) -> None:
        return None


def test_classify_domain_game() -> None:
    prd = "Build a playable browser game with score, controls, and restart."
    assert classify_domain(prd, "javascript") == "game"


def test_classify_domain_api() -> None:
    prd = "Create a REST API with endpoints, auth, status codes, and JSON responses."
    assert classify_domain(prd, "python") == "api"


def test_classify_domain_website() -> None:
    prd = "Build a responsive website with pages, layout, and browser navigation."
    assert classify_domain(prd, "javascript") == "website"


def test_classify_domain_generic_on_ambiguous_text() -> None:
    prd = "Implement project improvements and cleanup."
    assert classify_domain(prd, "") == "generic"


def test_website_contract_accepts_non_game_categories() -> None:
    items = [
        FeatureQueueItem(
            slug="project-scaffold",
            title="Project Scaffold",
            status="pending",
            feature_path="docs/features/2026-02-09-project-scaffold",
        ),
        FeatureQueueItem(
            slug="home-page-layout",
            title="Home Page Layout",
            status="pending",
            feature_path="docs/features/2026-02-09-home-page-layout",
        ),
        FeatureQueueItem(
            slug="interactive-contact-form",
            title="Interactive Contact Form",
            status="pending",
            feature_path="docs/features/2026-02-09-interactive-contact-form",
        ),
        FeatureQueueItem(
            slug="responsive-styling",
            title="Responsive Styling",
            status="pending",
            feature_path="docs/features/2026-02-09-responsive-styling",
        ),
        FeatureQueueItem(
            slug="content-fetching",
            title="Content Fetching",
            status="pending",
            feature_path="docs/features/2026-02-09-content-fetching",
        ),
        FeatureQueueItem(
            slug="website-test-suite",
            title="Website Test Suite",
            status="pending",
            feature_path="docs/features/2026-02-09-website-test-suite",
        ),
    ]
    failures = _collect_semantic_plan_failures(
        items,
        log=_Log(),
        contract=get_domain_contract("website"),
    )
    assert failures == []

