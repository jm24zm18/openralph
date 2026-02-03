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
    "# Test policy\n\n"
    "## Required actions\n"
    "1. You MUST execute the test command, not just identify it.\n"
    "2. Capture and report the full output.\n\n"
    "## Common test commands\n"
    "- Node.js: `npm test` or `yarn test`\n"
    "- Python: `pytest` or `python -m pytest`\n"
    "- Rust: `cargo test`\n"
    "- Go: `go test ./...`\n"
    "- Make: `make test`\n\n"
    "## Gate decision\n"
    "- Tests executed and passed -> PASS\n"
    "- Tests executed and failed -> FAIL\n"
    "- Test command exists but NOT executed -> FAIL\n"
    "- No test infrastructure at all -> PASS (with recommendation)\n",
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
