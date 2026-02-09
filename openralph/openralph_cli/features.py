from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from importlib import resources


@dataclass
class FeatureFolder:
    path: Path
    slug: str
    date_str: str
    title: str
    is_current: bool = False


def _read_template(name: str, fallback: str) -> str:
    try:
        return resources.files("openralph.templates").joinpath(name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return fallback

BRIEF_TEMPLATE = _read_template(
    "00-brief.md",
    "# {title}\n\n## Summary\n\n{description}\n\n## Why\n\n- TBD\n\n## Owner\n\n- TBD\n",
)

REQUIREMENTS_TEMPLATE = _read_template(
    "01-requirements.md",
    "# Requirements: {title}\n\n## Goals\n\n- TBD\n\n## Non-goals\n\n- TBD\n\n## Acceptance criteria\n\n- [ ] TBD\n\n## Dependencies\n\n- None\n",
)

TEST_PLAN_TEMPLATE = _read_template(
    "03-test-plan.md",
    "# Test Plan: {title}\n\n## Unit tests\n\n- TBD\n\n## Integration tests\n\n- TBD\n\n## Manual verification\n\n- [ ] TBD\n\n## Gate criteria\n\n- All unit tests pass\n- All integration tests pass\n- Manual verification complete\n",
)

BUG_BRIEF_TEMPLATE = "# Bug: {title}\n\n## Summary\n\n{description}\n\n## Impact\n\n- TBD\n\n## Owner\n\n- TBD\n"

BUG_REQUIREMENTS_TEMPLATE = (
    "# Bug Requirements: {title}\n\n"
    "## Reproduction steps\n\n- TBD\n\n"
    "## Expected behavior\n\n- TBD\n\n"
    "## Actual behavior\n\n- TBD\n\n"
    "## Acceptance criteria\n\n- [ ] Fix verified\n"
)

BUG_TEST_PLAN_TEMPLATE = (
    "# Bug Test Plan: {title}\n\n"
    "## Unit tests\n\n- TBD\n\n"
    "## Integration tests\n\n- TBD\n\n"
    "## Manual verification\n\n- [ ] TBD\n\n"
    "## Gate criteria\n\n- Tests pass\n- Reproduction no longer occurs\n"
)


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a URL-friendly slug."""
    # Lowercase and replace spaces with hyphens
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len]


def get_features_dir(repo: Path) -> Path:
    """Get the features directory path."""
    return repo / "docs" / "features"

def get_bugs_dir(repo: Path) -> Path:
    """Get the bugs directory path."""
    return repo / "docs" / "bugs"


def get_current_feature_file(repo: Path) -> Path:
    """Get the path to CURRENT_FEATURE file."""
    return repo / ".ralph" / "CURRENT_FEATURE"


def get_current_feature(repo: Path) -> Path | None:
    """Get the current feature folder path."""
    cf_file = get_current_feature_file(repo)
    if not cf_file.exists():
        return None
    try:
        rel_path = cf_file.read_text(encoding="utf-8").strip()
        if not rel_path:
            return None
        feature_path = repo / rel_path
        if feature_path.exists() and feature_path.is_dir():
            return feature_path
        return None
    except OSError:
        return None


def set_current_feature(repo: Path, feature_path: Path) -> None:
    """Set the current feature folder."""
    cf_file = get_current_feature_file(repo)
    cf_file.parent.mkdir(parents=True, exist_ok=True)
    rel_path = feature_path.relative_to(repo)
    cf_file.write_text(str(rel_path), encoding="utf-8")


def create_feature(repo: Path, title: str, description: str = "") -> FeatureFolder:
    """Create a new feature folder with required files."""
    features_dir = get_features_dir(repo)
    features_dir.mkdir(parents=True, exist_ok=True)

    date_str = date.today().strftime("%Y-%m-%d")
    slug = _slugify(title)
    folder_name = f"{date_str}-{slug}"
    feature_path = features_dir / folder_name

    # Check if folder already exists
    if feature_path.exists():
        # Add suffix
        suffix = 1
        while feature_path.exists():
            feature_path = features_dir / f"{folder_name}-{suffix}"
            suffix += 1

    feature_path.mkdir(parents=True, exist_ok=True)

    # Create required files
    brief_content = BRIEF_TEMPLATE.format(title=title, description=description or "TBD")
    (feature_path / "00-brief.md").write_text(brief_content, encoding="utf-8")

    req_content = REQUIREMENTS_TEMPLATE.format(title=title)
    (feature_path / "01-requirements.md").write_text(req_content, encoding="utf-8")

    test_content = TEST_PLAN_TEMPLATE.format(title=title)
    (feature_path / "03-test-plan.md").write_text(test_content, encoding="utf-8")

    # Set as current feature
    set_current_feature(repo, feature_path)

    return FeatureFolder(
        path=feature_path,
        slug=slug,
        date_str=date_str,
        title=title,
        is_current=True,
    )


def create_bug(repo: Path, title: str, description: str = "") -> FeatureFolder:
    """Create a new bug folder with required files."""
    bugs_dir = get_bugs_dir(repo)
    bugs_dir.mkdir(parents=True, exist_ok=True)

    date_str = date.today().strftime("%Y-%m-%d")
    slug = _slugify(title)
    folder_name = f"{date_str}-{slug}"
    bug_path = bugs_dir / folder_name

    if bug_path.exists():
        suffix = 1
        while bug_path.exists():
            bug_path = bugs_dir / f"{folder_name}-{suffix}"
            suffix += 1

    bug_path.mkdir(parents=True, exist_ok=True)

    brief_content = BUG_BRIEF_TEMPLATE.format(title=title, description=description or "TBD")
    (bug_path / "00-brief.md").write_text(brief_content, encoding="utf-8")

    req_content = BUG_REQUIREMENTS_TEMPLATE.format(title=title)
    (bug_path / "01-requirements.md").write_text(req_content, encoding="utf-8")

    test_content = BUG_TEST_PLAN_TEMPLATE.format(title=title)
    (bug_path / "03-test-plan.md").write_text(test_content, encoding="utf-8")

    set_current_feature(repo, bug_path)

    return FeatureFolder(
        path=bug_path,
        slug=slug,
        date_str=date_str,
        title=title,
        is_current=True,
    )


def list_features(repo: Path) -> list[FeatureFolder]:
    """List all feature folders."""
    features_dir = get_features_dir(repo)
    if not features_dir.exists():
        return []

    current = get_current_feature(repo)
    features: list[FeatureFolder] = []

    for folder in sorted(features_dir.iterdir()):
        if not folder.is_dir():
            continue
        name = folder.name
        # Parse date and slug from folder name (YYYY-MM-DD-slug)
        match = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", name)
        if match:
            date_str, slug = match.groups()
        else:
            date_str = ""
            slug = name

        # Try to read title from brief
        title = slug
        brief_path = folder / "00-brief.md"
        if brief_path.exists():
            try:
                content = brief_path.read_text(encoding="utf-8")
                # Extract title from first heading
                for line in content.split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            except OSError:
                pass

        features.append(FeatureFolder(
            path=folder,
            slug=slug,
            date_str=date_str,
            title=title,
            is_current=(current is not None and folder.resolve() == current.resolve()),
        ))

    return features


def get_feature_context(repo: Path) -> str | None:
    """Get context from current feature for use in prompts."""
    current = get_current_feature(repo)
    if current is None:
        return None

    parts = [f"## Current Feature: {current.name}\n"]

    for filename in ["00-brief.md", "01-requirements.md", "03-test-plan.md"]:
        file_path = current / filename
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"### {filename}\n{content}\n")
            except OSError:
                pass

    return "\n".join(parts) if len(parts) > 1 else None
