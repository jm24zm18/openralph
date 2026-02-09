# Repository Guidelines

## Project Structure & Module Organization
- `openralph/` is the Python package. CLI code lives in `openralph/openralph_cli/`, with entrypoint in `openralph/openralph_cli/cli.py`.
- `openralph/openralph_cli/memory/` contains the SQLite + embeddings subsystem.
- `openralph/openralph_cli/planner.py`, `issues.py`, and `prompts.py` power the auto-plan pipeline (planning, issue extraction, prompt builders).
- `docs/` holds `PRD.md`, `USAGE.md`, `ARCHITECTURE.md`, and feature specs under `docs/features/YYYY-MM-DD-slug/` (`00-brief.md`, `01-requirements.md`, `03-test-plan.md`).
- Runtime artifacts are created under `.ralph/` when you run `openralph init .` (not committed). Key files include `CURRENT_FEATURE`, `prd-answers.json`, `TEST_REPORT.md`, `REVIEW_REPORT.md`, `FINAL.md`, `DONE`, `LAST_GREEN.sha`, `feature-queue.json`, `issues.json`, and `logs/`.

## Build, Test, and Development Commands
- `pip install -e .` installs the project in editable mode.
- `openralph config init --scope global` initializes global config (one-time).
- `openralph init . --node-tooling local --create-venv` bootstraps a repo and writes `.ralph/` artifacts.
- `openralph doctor .` runs the built-in health check (current primary validation path).
- `openralph run . "Implement X"` executes the orchestration loop.
- `openralph run . "Implement X" --auto full` runs PRD generation + planning + builds all features.
- `openralph prd generate .` generates `docs/PRD.md` from repo context.
- `openralph prd qa .` runs PRD Q&A and writes `.ralph/prd-answers.json`.
- `openralph prd show .` prints the current PRD.
- `openralph feature new . "Title" --description "Short desc"` creates a feature folder and sets `CURRENT_FEATURE`.
- `openralph feature list .`, `openralph feature current .`, `openralph feature context .` manage feature specs.

## Coding Style & Naming Conventions
- Python 3.10+, 4-space indentation, follow PEP 8.
- Use type hints everywhere and prefer `from __future__ import annotations` in new modules.
- No docstrings; favor clear, self-documenting names.
- Naming: functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`, private helpers prefixed with `_`.
- Use `pathlib.Path` for file paths and handle Windows via `os.name == "nt"` or `sys.platform.startswith("win")`.

## Testing Guidelines
- No formal automated test suite exists yet.
- Validation is manual via:
  - `openralph doctor .` (health checks)
  - `openralph config show .` (config validation)
  - `openralph run . "..."`
- When adding tests, place them under a new `tests/` directory and name files `test_*.py`.

## Commit & Pull Request Guidelines
- Commit history is mixed; there is no strict convention. Use short, imperative summaries (e.g., “Add config validation”).
- Prefer one logical change per commit.
- PRs should describe the change, list any new commands, and note manual verification steps (e.g., “ran `openralph doctor .`”).

## Configuration & Dependencies
- Config precedence: CLI flags > env vars > `.openralph.toml` > global config.
- External services: Ollama must be running for embeddings; Git is required for checkpoints; Node.js/npm are optional for tooling installs.
