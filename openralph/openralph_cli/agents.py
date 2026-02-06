from __future__ import annotations
from pathlib import Path


AGENTS_MD_TEMPLATE = """# Agent Operating Guide

This repository is designed to be worked on by automated agents (with optional human-in-the-loop).
This document explains the structure, rules, and conventions agents must follow.

---

## 1. High-level structure

Key folders:

- **docs/PRD.md**
  Product Requirements Document.
  Source of truth for goals, non-goals, and scope.

- **docs/features/**
  Feature- and bug-specific specifications.
  Each subfolder represents one work item.

- **.ralph/**
  Agent loop state, memory, and coordination files.
  Do not delete unless you know what you're doing.

---

## 2. Feature specification folders

All work must be associated with a feature folder:

```
docs/features/YYYY-MM-DD-<slug>/
```

Required files:
- `00-brief.md` — short description of what/why
- `01-requirements.md` — goals, non-goals, acceptance criteria
- `03-test-plan.md` — how this feature is validated

Optional files:
- `02-design.md`
- `04-release-notes.md`
- `05-retro.md`

The active feature is recorded in:
```
.ralph/CURRENT_FEATURE
```

Agents must read and update the active feature folder when making changes.

---

## 3. Agent loop artifacts (.ralph)

Important files in `.ralph/`:

- **HUMAN_REQUEST.md**
  Questions that require a response (human or agent).

- **HUMAN_RESPONSE.md**
  Answers to HUMAN_REQUEST.md.

- **TEST_REPORT.md**
  Output from the testing agent.
  Must include `Gate: PASS` or `Gate: FAIL`.

- **STACK.md**
  Selected tech stack for this repo. Agents should not change it unless required.

- **REVIEW_REPORT.md**
  Product/user review feedback.

- **FINAL.md**
  Final summary when work is complete.

- **DONE**
  Presence of this file signals the loop should stop (only allowed if gate is PASS).

- **memory.sqlite3**
  Per-project semantic memory (SQLite + embeddings).

---

## 4. Gates and rules

### Lint/Test Gate
Work is considered valid only if:
- Required linting, typechecking, and tests pass for detected stacks.
- The testing agent reports `Gate: PASS`.

If the gate fails:
- The next iteration must focus **only** on fixing the gate.

DONE is not allowed while the gate is FAIL.

---

## 5. Dependency installation policy

Agents must follow the minimal install policy:

- Prefer project-declared tooling and lockfiles.
- Install only what is required to run lint/tests.
- Never upgrade dependencies automatically.
- If install strategy is ambiguous, ask via HUMAN_REQUEST.md.

See:
```
.ralph/install-policy.md
```

---

## 6. Memory and search

This repo maintains per-project memory:

- Stored in `.ralph/memory.sqlite3`
- Indexed from:
  - source files
  - markdown docs (PRD, features, reports)
- Used to retrieve relevant context during iterations

Memory is updated incrementally after changes.

---

## 7. Git and versioning

- Work is done on an `openralph/*` branch.
- Each iteration is committed.
- The last known good state is recorded and tagged.
- Rollbacks may occur only on `openralph/*` branches.

Agents must not push, rebase, or force-push.

---

## 8. When to ask for help

Agents must ask via `HUMAN_REQUEST.md` when:
- Requirements are unclear or conflicting
- Dependency install strategy is ambiguous
- A decision affects scope, UX, or compatibility
- Tests require choosing a runtime or platform

Guessing is discouraged.

---

## 9. Completion checklist

Before creating `.ralph/DONE`, ensure:
- Gate is PASS
- Acceptance criteria in the feature folder are satisfied
- docs/PRD.md is still accurate (or updated)
- FINAL.md summarizes what changed and how to verify

---

## 10. For humans

Humans can:
- Answer questions in HUMAN_RESPONSE.md
- Edit PRD or feature specs directly
- Remove DONE to resume the loop

This system is designed to be inspectable, auditable, and interruptible.
"""


def generate_agents_md(repo: Path, force: bool = False) -> Path:
    """Generate AGENTS.md in the repository root."""
    agents_path = repo / "AGENTS.md"

    if agents_path.exists() and not force:
        raise FileExistsError(f"AGENTS.md already exists at {agents_path}. Use --force to overwrite.")

    agents_path.write_text(AGENTS_MD_TEMPLATE, encoding="utf-8")
    return agents_path


def agents_md_exists(repo: Path) -> bool:
    """Check if AGENTS.md exists."""
    return (repo / "AGENTS.md").exists()
