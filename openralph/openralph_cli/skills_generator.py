from __future__ import annotations
from pathlib import Path

def _write(path: Path, content: str, *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return
    path.write_text(content.rstrip() + "\n", encoding="utf-8")

def write_default_skills(repo: Path, *, force: bool) -> None:
    repo = repo.resolve()
    base = repo / ".opencode" / "skills"
    _write(base / "openralph-loop" / "SKILL.md", SKILL_LOOP, force=force)
    _write(base / "openralph-gates" / "SKILL.md", SKILL_GATES, force=force)
    _write(base / "openralph-prd" / "SKILL.md", SKILL_PRD, force=force)
    _write(base / "openralph-human" / "SKILL.md", SKILL_HUMAN, force=force)
    _write(base / "openralph-git" / "SKILL.md", SKILL_GIT, force=force)
    _write(base / "openralph-memory" / "SKILL.md", SKILL_MEMORY, force=force)

SKILL_LOOP = """---
name: openralph-loop
description: Run the OpenRalph loop: plan, implement, gate, checkpoint, and ask humans when needed.
compatibility: opencode
---
## Contract
- Work in small steps.
- After each step: run the configured gates (lint/tests).
- If gates fail repeatedly: rollback to last green checkpoint and try an alternative.
- Ask for human input only when blocked by ambiguity or missing product decisions.
"""

SKILL_GATES = """---
name: openralph-gates
description: Lint/test gate policy with fallbacks based on detected tooling or file extensions.
compatibility: opencode
---
## Gate order (recommended)
1) Format/lint (fast)
2) Unit tests
3) E2E (only if configured, e.g. Playwright)
"""

SKILL_PRD = """---
name: openralph-prd
description: Generate and maintain docs/PRD.md via Q/A; supports regenerate and partial updates.
compatibility: opencode
---
## First-time PRD creation
- Run a question/answer session.
- If OpenRalph user is unavailable, the agent may propose answers but must mark assumptions.
"""

SKILL_HUMAN = """---
name: openralph-human
description: Ask the human for input with minimal friction; propose defaults and clarify decisions.
compatibility: opencode
---
## How to ask
- Ask 1–3 focused questions max.
- Provide recommended defaults.
"""

SKILL_GIT = """---
name: openralph-git
description: Git workflow: branch naming, checkpoint commits after green gates, rollback on repeated failures.
compatibility: opencode
---
## Checkpoints
- After gates pass: commit as "openralph: checkpoint - <summary>"
"""

SKILL_MEMORY = """---
name: openralph-memory
description: Project memory usage: query, reindex, and keep retrieval within a budget.
compatibility: opencode
---
## Query
- Query memory for repo conventions and prior work.
"""
