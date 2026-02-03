from __future__ import annotations
from pathlib import Path
from importlib import resources

def _read_template(name: str, fallback: str) -> str:
    try:
        return resources.files("openralph.templates").joinpath(name).read_text(encoding="utf-8")
    except Exception:
        return fallback

TEST_POLICY = _read_template(
    "test-policy.md",
    "# Test policy (template)\n- Prefer project-defined test commands (pyproject/package.json).\n- Fall back to extension-based defaults.\n",
)

INSTALL_POLICY = _read_template(
    "install-policy.md",
    "# Install policy (template)\n- Prefer local installs (venv for python, .ralph/node-tools for node).\n- Avoid global installs unless explicitly allowed.\n",
)

def ensure_policies(repo: Path) -> None:
    ralph = repo / ".ralph"
    ralph.mkdir(parents=True, exist_ok=True)
    tp = ralph / "test-policy.md"
    ip = ralph / "install-policy.md"
    if not tp.exists():
        tp.write_text(TEST_POLICY, encoding="utf-8")
    if not ip.exists():
        ip.write_text(INSTALL_POLICY, encoding="utf-8")
