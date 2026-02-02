from __future__ import annotations
from pathlib import Path

TEST_POLICY = """# Test policy (template)
- Prefer project-defined test commands (pyproject/package.json).
- Fall back to extension-based defaults.
"""

INSTALL_POLICY = """# Install policy (template)
- Prefer local installs (venv for python, .ralph/node-tools for node).
- Avoid global installs unless explicitly allowed.
"""

def ensure_policies(repo: Path) -> None:
    ralph = repo / ".ralph"
    ralph.mkdir(parents=True, exist_ok=True)
    tp = ralph / "test-policy.md"
    ip = ralph / "install-policy.md"
    if not tp.exists():
        tp.write_text(TEST_POLICY, encoding="utf-8")
    if not ip.exists():
        ip.write_text(INSTALL_POLICY, encoding="utf-8")
