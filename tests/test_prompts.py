from __future__ import annotations

from openralph.openralph_cli.prompts import TEST_SYSTEM, build_builder_prompt, build_review_prompt


def test_build_builder_prompt_auto_mode_disables_human_requests() -> None:
    prompt = build_builder_prompt(
        user_prompt="Build feature X",
        memory_context="",
        feature_context="",
        stack_context="",
        test_report="",
        review_report="",
        human_response="",
        final_path=".ralph/FINAL.md",
        open_issues="",
        auto_mode=True,
    )
    assert "do not ask for human input" in prompt
    assert "write to .ralph/HUMAN_REQUEST.md and stop" not in prompt


def test_build_review_prompt_auto_mode_uses_assumptions_section() -> None:
    prompt = build_review_prompt(
        prd_excerpt="PRD",
        feature_context="Feature",
        test_report="Report",
        git_ctx="Diff",
        report_path=".ralph/REVIEW_REPORT.md",
        auto_mode=True,
    )
    assert "## Open assumptions (auto mode)" in prompt
    assert "do NOT write .ralph/HUMAN_REQUEST.md" in prompt
    assert "## Questions (if any)" not in prompt


def test_test_system_mentions_browser_tools() -> None:
    assert "browser_navigate" in TEST_SYSTEM
    assert "browser_console" in TEST_SYSTEM
