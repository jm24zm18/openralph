from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from openralph.openralph_cli.loop.gate import (
    _find_forbidden_test_installs,
    _find_entry_points,
    _run_smoke_checks,
    _smoke_check_dependency_paths,
    _smoke_check_entry_points,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "project"
    r.mkdir()
    return r


def _make_venv(repo: Path) -> Path:
    venv = repo / ".venv"
    venv.mkdir()
    bin_dir = venv / ("Scripts" if sys.platform.startswith("win") else "bin")
    bin_dir.mkdir()
    py = bin_dir / ("python.exe" if sys.platform.startswith("win") else "python")
    py.write_text("", encoding="utf-8")
    py.chmod(0o755)
    return py


# --- _smoke_check_dependency_paths ---


def test_no_requirements_returns_empty(repo: Path) -> None:
    _make_venv(repo)
    assert _smoke_check_dependency_paths(repo) == []


def test_no_venv_returns_empty(repo: Path) -> None:
    (repo / "requirements.txt").write_text("requests\n", encoding="utf-8")
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="/usr/lib/python/site-packages/requests/__init__.py\n", stderr=""
    )
    with patch("openralph.openralph_cli.loop.gate.subprocess.run", return_value=fake_result):
        assert _smoke_check_dependency_paths(repo) == []


def test_clean_dep_passes(repo: Path) -> None:
    (repo / "requirements.txt").write_text("os-sys-test-pkg\n", encoding="utf-8")
    _make_venv(repo)
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="/usr/lib/python/site-packages/os_sys_test_pkg/__init__.py\n", stderr=""
    )
    with patch("openralph.openralph_cli.loop.gate.subprocess.run", return_value=fake_result):
        failures = _smoke_check_dependency_paths(repo)
    assert failures == []


def test_shadow_detected(repo: Path) -> None:
    (repo / "requirements.txt").write_text("pygame\n", encoding="utf-8")
    _make_venv(repo)
    shadow_dir = repo / "pygame"
    shadow_dir.mkdir()
    (shadow_dir / "__init__.py").write_text("", encoding="utf-8")
    shadow_file = str((shadow_dir / "__init__.py").resolve())
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=shadow_file + "\n", stderr=""
    )
    with patch("openralph.openralph_cli.loop.gate.subprocess.run", return_value=fake_result):
        failures = _smoke_check_dependency_paths(repo)
    assert len(failures) == 1
    assert "shadow" in failures[0]
    assert "pygame" in failures[0]


def test_import_failure_reported(repo: Path) -> None:
    (repo / "requirements.txt").write_text("nonexistent\n", encoding="utf-8")
    _make_venv(repo)
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ModuleNotFoundError"
    )
    with patch("openralph.openralph_cli.loop.gate.subprocess.run", return_value=fake_result):
        failures = _smoke_check_dependency_paths(repo)
    assert len(failures) == 1
    assert "import failed" in failures[0]


def test_pytest_dependency_is_ignored_in_runtime_smoke(repo: Path) -> None:
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    _make_venv(repo)
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ModuleNotFoundError: No module named 'pytest'"
    )
    with patch("openralph.openralph_cli.loop.gate.subprocess.run", return_value=fake_result):
        failures = _smoke_check_dependency_paths(repo)
    assert failures == []


def test_readme_missing_script_detected(repo: Path) -> None:
    (repo / "README.md").write_text(
        'Run with `python3 beta_app/notes_cli.py add "x"`.\n',
        encoding="utf-8",
    )
    failures = _run_smoke_checks(repo, "python")
    assert any("missing script" in f for f in failures)


def test_forbidden_test_install_detection(repo: Path) -> None:
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    bad_test = tests_dir / "test_env.py"
    bad_test.write_text("def test_x():\n    assert 'pip install -e .' is not None\n", encoding="utf-8")
    findings = _find_forbidden_test_installs(repo)
    assert len(findings) == 1
    assert "forbidden install command" in findings[0]


# --- _find_entry_points ---


def test_find_python_entry_points(repo: Path) -> None:
    (repo / "main.py").write_text("print('hi')", encoding="utf-8")
    (repo / "app.py").write_text("print('hi')", encoding="utf-8")
    entries = _find_entry_points(repo, "python")
    assert len(entries) == 2
    names = {e.name for e in entries}
    assert "main.py" in names
    assert "app.py" in names


def test_find_python_dunder_main(repo: Path) -> None:
    pkg = repo / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__main__.py").write_text("print('hi')", encoding="utf-8")
    entries = _find_entry_points(repo, "python")
    assert len(entries) == 1
    assert entries[0].name == "__main__.py"


def test_find_node_entry_from_package_json(repo: Path) -> None:
    (repo / "package.json").write_text(json.dumps({"main": "server.js"}), encoding="utf-8")
    (repo / "server.js").write_text("console.log('hi')", encoding="utf-8")
    entries = _find_entry_points(repo, "node")
    assert len(entries) == 1
    assert entries[0].name == "server.js"


def test_find_node_fallback(repo: Path) -> None:
    (repo / "index.js").write_text("console.log('hi')", encoding="utf-8")
    entries = _find_entry_points(repo, "node")
    assert len(entries) == 1
    assert entries[0].name == "index.js"


def test_no_entry_points_not_failure(repo: Path) -> None:
    entries = _find_entry_points(repo, "python")
    assert entries == []


def test_entry_points_limited_to_three(repo: Path) -> None:
    for name in ("main.py", "app.py", "run.py", "game.py"):
        (repo / name).write_text("x = 1", encoding="utf-8")
    entries = _find_entry_points(repo, "python")
    assert len(entries) == 3


# --- _smoke_check_entry_points ---


def test_valid_entry_point_passes(repo: Path) -> None:
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    failures = _smoke_check_entry_points(repo, "python")
    assert failures == []


def test_syntax_error_caught(repo: Path) -> None:
    (repo / "main.py").write_text("def f(\n", encoding="utf-8")
    failures = _smoke_check_entry_points(repo, "python")
    assert len(failures) == 1
    assert "compile error" in failures[0]


def test_no_entries_returns_empty(repo: Path) -> None:
    failures = _smoke_check_entry_points(repo, "python")
    assert failures == []


# --- _run_smoke_checks (integration) ---


def test_run_smoke_checks_clean(repo: Path) -> None:
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    failures = _run_smoke_checks(repo, "python")
    assert failures == []


def test_run_smoke_checks_combines_failures(repo: Path) -> None:
    (repo / "requirements.txt").write_text("badpkg\n", encoding="utf-8")
    _make_venv(repo)
    (repo / "main.py").write_text("def f(\n", encoding="utf-8")
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ModuleNotFoundError"
    )
    with patch("openralph.openralph_cli.loop.gate.subprocess.run", return_value=fake_result):
        failures = _run_smoke_checks(repo, "python")
    assert len(failures) >= 2
