from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class StackChoice:
    name: str
    reason: str
    signals: list[str]


STACK_MARKERS: dict[str, list[str]] = {
    "node": ["package.json", "pnpm-lock.yaml", "yarn.lock"],
    "python": ["pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "dotnet": [".sln", ".csproj", ".fsproj"],
    "java": ["pom.xml", "build.gradle", "gradlew", "build.gradle.kts"],
    "ruby": ["Gemfile"],
    "php": ["composer.json"],
    "elixir": ["mix.exs"],
    "swift": ["Package.swift"],
    "c-cpp": ["CMakeLists.txt", "meson.build", "Makefile"],
}


def _find_markers(repo: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for stack, markers in STACK_MARKERS.items():
        hits: list[str] = []
        for marker in markers:
            if marker.startswith(".") or marker.endswith(".csproj") or marker.endswith(".fsproj") or marker.endswith(".sln"):
                # glob patterns in root for extensions
                if any(repo.glob(f"*{marker}")):
                    hits.append(marker)
            else:
                if (repo / marker).exists():
                    hits.append(marker)
        if hits:
            found[stack] = hits
    return found


def detect_stack(repo: Path) -> list[StackChoice]:
    signals = _find_markers(repo)
    choices: list[StackChoice] = []
    for stack, hits in signals.items():
        choices.append(StackChoice(
            name=stack,
            reason=f"Detected {', '.join(hits)}",
            signals=hits,
        ))
    return choices


def read_stack_file(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("stack"):
                return str(data["stack"]).strip()
        except Exception:
            pass
    for line in text.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            if key.strip().lower() == "stack":
                return val.strip()
    return text.splitlines()[0].strip()


def write_stack_file(path: Path, choice: StackChoice) -> None:
    content = (
        f"stack: {choice.name}\n"
        f"reason: {choice.reason}\n"
        f"signals: {', '.join(choice.signals)}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def default_test_command(stack: str, repo: Path) -> str | None:
    stack = stack.strip().lower()
    if stack == "node":
        if (repo / "pnpm-lock.yaml").exists():
            return "pnpm test"
        if (repo / "yarn.lock").exists():
            return "yarn test"
        if (repo / "package.json").exists():
            return "npm test"
        return None
    if stack == "python":
        return "python -m pytest -q"
    if stack == "rust":
        return "cargo test"
    if stack == "go":
        return "go test ./..."
    if stack == "dotnet":
        return "dotnet test"
    if stack == "java":
        if (repo / "gradlew").exists():
            return "./gradlew test"
        if (repo / "mvnw").exists():
            return "./mvnw test"
        return "mvn test"
    if stack == "ruby":
        return "bundle exec rspec"
    if stack == "php":
        return "phpunit"
    if stack == "elixir":
        return "mix test"
    if stack == "swift":
        return "swift test"
    if stack == "c-cpp":
        return None
    return None
