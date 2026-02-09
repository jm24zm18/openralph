from __future__ import annotations

from pathlib import Path
import ast
import importlib.util
import json
import re
import shlex
import subprocess
import sys

_TEST_RUNNER_PACKAGES = {"pytest", "unittest", "nose", "nose2", "tox", "coverage", "hypothesis"}
_FORBIDDEN_TEST_INSTALL_PATTERNS = [
    re.compile(r"\bpython(?:3)?\s+-m\s+pip\s+install\s+-e\s+\.", re.IGNORECASE),
    re.compile(r"\bpip(?:3)?\s+install\s+-e\s+\.", re.IGNORECASE),
]


def _module_exists_in_repo(repo: Path, name: str) -> bool:
    root = repo / name
    if (repo / f"{name}.py").exists():
        return True
    if root.is_dir() and (root / "__init__.py").exists():
        return True
    return False


def _is_stdlib_module(name: str) -> bool:
    stdlib = getattr(sys, "stdlib_module_names", set())
    return name in stdlib


def _find_venv_python(repo: Path) -> Path | None:
    for venv_name in (".venv", "venv"):
        venv_dir = repo / venv_name
        if not venv_dir.is_dir():
            continue
        if sys.platform.startswith("win"):
            py = venv_dir / "Scripts" / "python.exe"
        else:
            py = venv_dir / "bin" / "python"
        if py.exists():
            return py
    return None


def _runtime_python(repo: Path) -> Path:
    py = _find_venv_python(repo)
    if py is not None:
        return py
    return Path(sys.executable)


def _is_installed_module(name: str, venv_python: Path | None = None) -> bool:
    if venv_python is not None:
        try:
            r = subprocess.run(
                [str(venv_python), "-c", f"__import__({name!r})"],
                capture_output=True,
                timeout=10,
            )
            return r.returncode == 0
        except subprocess.SubprocessError:
            return False
        except OSError:
            return False
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _extract_imports(path: Path, imports: set[str]) -> None:
    try:
        node = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (ValueError, SyntaxError):
        return
    for item in ast.walk(node):
        if isinstance(item, ast.Import):
            for alias in item.names:
                if alias.name:
                    imports.add(alias.name.split(".")[0])
        elif isinstance(item, ast.ImportFrom):
            if item.level and item.level > 0:
                continue
            if item.module:
                imports.add(item.module.split(".")[0])


def _collect_test_imports(repo: Path) -> set[str]:
    imports: set[str] = set()
    tests_dir = repo / "tests"
    if tests_dir.exists():
        for path in tests_dir.rglob("*.py"):
            _extract_imports(path, imports)
    for path in repo.glob("test_*.py"):
        _extract_imports(path, imports)
    return imports


def _declared_dependency_modules(repo: Path) -> set[str]:
    names: set[str] = set()
    for rel in ("requirements.txt", "requirements-dev.txt"):
        req = repo / rel
        if not req.exists():
            continue
        for raw in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            line = line.split(";", 1)[0].strip()
            line = line.split("[", 1)[0].strip()
            base = re.split(r"[<>=!~\s]", line, maxsplit=1)[0].strip()
            if not base:
                continue
            names.add(base.lower().replace("-", "_"))
    return names


def _find_shadowed_dependency_imports(repo: Path) -> list[str]:
    imports = _collect_test_imports(repo)
    if not imports:
        return []
    declared = _declared_dependency_modules(repo)
    if not declared:
        return []
    shadowed: list[str] = []
    for name in sorted(imports):
        norm = name.lower().replace("-", "_")
        if norm not in declared:
            continue
        if _module_exists_in_repo(repo, name):
            shadowed.append(name)
    return shadowed


def _find_missing_test_imports(repo: Path) -> list[str]:
    missing: list[str] = []
    venv_python = _find_venv_python(repo)
    for name in sorted(_collect_test_imports(repo)):
        if name in _TEST_RUNNER_PACKAGES:
            continue
        if _module_exists_in_repo(repo, name):
            continue
        if _is_stdlib_module(name) or _is_installed_module(name, venv_python):
            continue
        missing.append(name)
    for name in _find_shadowed_dependency_imports(repo):
        missing.append(f"{name} (shadowed local module)")
    return missing


def _smoke_check_dependency_paths(repo: Path, timeout: int = 10) -> list[str]:
    declared = _declared_dependency_modules(repo)
    if not declared:
        return []
    runtime_python = _runtime_python(repo)
    repo_resolved = repo.resolve()
    failures: list[str] = []
    for name in sorted(declared):
        if name in _TEST_RUNNER_PACKAGES:
            continue
        if _is_stdlib_module(name):
            continue
        try:
            r = subprocess.run(
                [str(runtime_python), "-c",
                 f"import {name}; print(getattr({name}, '__file__', '') or '')"],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.SubprocessError:
            failures.append(f"{name}: import timed out or subprocess error")
            continue
        except OSError as e:
            failures.append(f"{name}: smoke runtime unavailable ({e})")
            continue
        if r.returncode != 0:
            stderr = r.stderr.strip()[:120]
            if name == "pytest":
                failures.append(
                    f"pytest: missing in runtime {runtime_python} ({stderr or 'import failed'})"
                )
            else:
                failures.append(f"{name}: import failed ({stderr})")
            continue
        mod_file = r.stdout.strip()
        if mod_file:
            try:
                mod_path = Path(mod_file).resolve()
                if mod_path.is_relative_to(repo_resolved):
                    failures.append(f"{name}: resolves to local file {mod_path.relative_to(repo_resolved)} (shadow)")
            except (ValueError, OSError):
                pass
    return failures


def _find_entry_points(repo: Path, stack: str) -> list[Path]:
    entries: list[Path] = []
    stack = stack.strip().lower()
    if stack == "node":
        pkg = repo / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                main = data.get("main", "")
                if main:
                    ep = repo / main
                    if ep.exists():
                        entries.append(ep)
            except (json.JSONDecodeError, OSError):
                pass
        if not entries:
            for name in ("index.js", "app.js"):
                p = repo / name
                if p.exists():
                    entries.append(p)
    else:
        for name in ("main.py", "app.py", "run.py", "game.py"):
            p = repo / name
            if p.exists():
                entries.append(p)
        for child in repo.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                dunder_main = child / "__main__.py"
                if dunder_main.exists():
                    entries.append(dunder_main)
    return entries[:3]


def _smoke_check_entry_points(repo: Path, stack: str, timeout: int = 10) -> list[str]:
    entries = _find_entry_points(repo, stack)
    if not entries:
        return []
    failures: list[str] = []
    stack = stack.strip().lower()
    runtime_python = _runtime_python(repo)
    for ep in entries:
        rel = ep.relative_to(repo)
        if stack == "node":
            try:
                r = subprocess.run(
                    ["node", "--check", str(ep)],
                    capture_output=True, text=True, timeout=timeout,
                    cwd=str(repo),
                )
                if r.returncode != 0:
                    failures.append(f"{rel}: syntax error ({r.stderr.strip()[:120]})")
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
        else:
            try:
                r = subprocess.run(
                    [str(runtime_python), "-c",
                     f"import py_compile; py_compile.compile({str(ep)!r}, doraise=True)"],
                    capture_output=True, text=True, timeout=timeout,
                    cwd=str(repo),
                )
                if r.returncode != 0:
                    failures.append(f"{rel}: compile error ({r.stderr.strip()[:120]})")
            except OSError as e:
                failures.append(f"{rel}: compile runtime unavailable ({e})")
            except subprocess.SubprocessError:
                failures.append(f"{rel}: compile check timed out")
    return failures


def _run_smoke_checks(repo: Path, stack: str, timeout: int = 10) -> list[str]:
    failures: list[str] = []
    failures.extend(_smoke_check_dependency_paths(repo, timeout))
    failures.extend(_smoke_check_entry_points(repo, stack, timeout))
    failures.extend(_verify_readme_commands(repo))
    return failures


def _verify_readme_commands(repo: Path) -> list[str]:
    readme = repo / "README.md"
    if not readme.exists():
        return []

    text = readme.read_text(encoding="utf-8", errors="ignore")
    commands: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("$ "):
            commands.append(line[2:].strip())
            continue
        if line.startswith("python ") or line.startswith("python3 "):
            commands.append(line)
    for cmd in re.findall(r"`([^`]+)`", text):
        c = cmd.strip()
        if c.startswith("python ") or c.startswith("python3 "):
            commands.append(c)

    failures: list[str] = []
    for command in commands:
        try:
            parts = shlex.split(command)
        except ValueError:
            continue
        if len(parts) < 2 or parts[0] not in {"python", "python3"}:
            continue
        target = parts[1]
        if target == "-m":
            continue
        if not target.endswith(".py"):
            continue
        if target.startswith("-"):
            continue
        script_path = (repo / target).resolve()
        if not script_path.exists() or not script_path.is_file():
            failures.append(f"README command references missing script: `{command}`")
    return failures


def _find_forbidden_test_installs(repo: Path) -> list[str]:
    candidates: list[Path] = []
    tests_dir = repo / "tests"
    if tests_dir.exists():
        for path in tests_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".sh", ".md", ".txt", ".yaml", ".yml"}:
                candidates.append(path)
    for path in repo.glob("test_*"):
        if path.is_file() and path.suffix.lower() in {".py", ".sh", ".md", ".txt"}:
            candidates.append(path)

    findings: list[str] = []
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _FORBIDDEN_TEST_INSTALL_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            rel = path.relative_to(repo)
            findings.append(f"{rel}: forbidden install command '{match.group(0)}'")
            break
    return findings


def _parse_gate(report_text: str) -> bool | None:
    pattern = re.compile(
        r"^\s*(?:#+\s*)?Gate\s*[:\-]\s*(PASS|FAIL)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(report_text)
    if not m:
        return None
    return m.group(1).upper() == "PASS"
