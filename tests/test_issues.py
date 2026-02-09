from __future__ import annotations

from openralph.openralph_cli.issues import (
    extract_issues_from_review_report,
    extract_issues_from_test_report,
)


def test_extract_issues_from_test_report() -> None:
    report = "FAILED test_a.py::test_x - AssertionError: nope\n"
    issues = extract_issues_from_test_report(report, iteration=1, feature_slug="feat")
    assert len(issues) == 1
    assert issues[0].source == "test"


def test_extract_issues_from_review_report() -> None:
    report = "## Risks\n- Missing retries in API client\n"
    issues = extract_issues_from_review_report(report, iteration=1, feature_slug="feat")
    assert len(issues) == 1
    assert issues[0].source == "review"
