from __future__ import annotations

from pathlib import Path

from openralph.openralph_cli.features import create_feature, get_current_feature, get_feature_context


def test_create_feature_sets_current(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    feature = create_feature(repo, "Test Feature", description="Desc")
    current = get_current_feature(repo)

    assert current == feature.path
    ctx = get_feature_context(repo)
    assert "Test Feature" in ctx
