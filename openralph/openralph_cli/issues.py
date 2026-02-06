from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict

from .paths import Paths


@dataclass
class Issue:
    id: str            # short hash for deduplication
    source: str        # "test" | "review"
    description: str
    file_path: str     # file reference if known, else ""
    iteration: int
    feature_slug: str
    status: str        # "open" | "fixed" | "wontfix"


def _make_id(source: str, description: str) -> str:
    raw = f"{source}:{description.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def load_issues(paths: Paths) -> list[Issue]:
    issues_path = paths.issues
    if not issues_path.exists():
        return []
    try:
        data = json.loads(issues_path.read_text(encoding="utf-8"))
        return [
            Issue(
                id=it["id"],
                source=it["source"],
                description=it["description"],
                file_path=it.get("file_path", ""),
                iteration=it.get("iteration", 0),
                feature_slug=it.get("feature_slug", ""),
                status=it.get("status", "open"),
            )
            for it in data
        ]
    except Exception:
        return []


def save_issues(paths: Paths, issues: list[Issue]) -> None:
    issues_path = paths.issues
    issues_path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(i) for i in issues]
    issues_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Extraction from reports ─────────────────────────────────────────────

_FAIL_PATTERNS = [
    re.compile(r"^(FAIL|ERROR|FAILED)\b.*", re.IGNORECASE),
    re.compile(r"(AssertionError|AssertionError|TypeError|ValueError|ImportError|ModuleNotFoundError):?\s+.*"),
    re.compile(r"^E\s+\w+Error:.*"),  # pytest-style error lines
]

_FILE_REF = re.compile(r"([\w/._-]+\.(?:py|js|ts|jsx|tsx)):(\d+)")


def extract_issues_from_test_report(
    report_text: str,
    iteration: int,
    feature_slug: str,
) -> list[Issue]:
    issues: list[Issue] = []
    for line in report_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for pat in _FAIL_PATTERNS:
            if pat.search(stripped):
                file_ref = ""
                m = _FILE_REF.search(stripped)
                if m:
                    file_ref = f"{m.group(1)}:{m.group(2)}"
                issues.append(Issue(
                    id=_make_id("test", stripped[:200]),
                    source="test",
                    description=stripped[:300],
                    file_path=file_ref,
                    iteration=iteration,
                    feature_slug=feature_slug,
                    status="open",
                ))
                break  # one match per line
    return issues


def extract_issues_from_review_report(
    report_text: str,
    iteration: int,
    feature_slug: str,
) -> list[Issue]:
    issues: list[Issue] = []
    in_risks = False
    in_questions = False

    for line in report_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Risks") or stripped.startswith("## Questions"):
            in_risks = "Risks" in stripped
            in_questions = "Questions" in stripped
            continue
        if stripped.startswith("## "):
            in_risks = False
            in_questions = False
            continue

        if (in_risks or in_questions) and stripped.startswith("- "):
            content = stripped[2:].strip()
            if content and content.lower() not in ("tbd", "none", "n/a"):
                issues.append(Issue(
                    id=_make_id("review", content[:200]),
                    source="review",
                    description=content[:300],
                    file_path="",
                    iteration=iteration,
                    feature_slug=feature_slug,
                    status="open",
                ))

    return issues


def format_open_issues_for_prompt(issues: list[Issue], feature_slug: str = "") -> str:
    """Format open issues as text for injection into builder prompt."""
    open_issues = [
        i for i in issues
        if i.status == "open"
        and (not feature_slug or i.feature_slug == feature_slug)
    ]
    if not open_issues:
        return ""
    lines = []
    for i in open_issues:
        ref = f" in {i.file_path}" if i.file_path else ""
        lines.append(f"- [{i.source}]{ref} {i.description}")
    return "\n".join(lines)
