from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

MANAGED_START = "# === openralph (managed) ==="
MANAGED_END = "# === /openralph (managed) ==="

@dataclass(frozen=True)
class GitignoreOptions:
    ignore_reports: bool = True
    track_current_feature: bool = True
    node_tooling: str = "global"  # global|local
    playwright: bool = True
    ignore_venvs: bool = True

def render_managed_block(opts: GitignoreOptions) -> str:
    lines: list[str] = []
    lines.append(MANAGED_START)
    lines.append("# DO NOT EDIT INSIDE THIS BLOCK (use: openralph gitignore sync)")
    lines.append("")
    lines.append(".ralph/*")
    lines.append("!.ralph/test-policy.md")
    lines.append("!.ralph/install-policy.md")
    if opts.track_current_feature:
        lines.append("!.ralph/CURRENT_FEATURE")
    lines.append(".ralph/logs/")
    lines.append(".ralph/*.diff")
    lines.append(".ralph/*.patch")
    lines.append(".ralph/memory.sqlite3")
    lines.append(".ralph/memory.sqlite3-wal")
    lines.append(".ralph/memory.sqlite3-shm")
    lines.append(".ralph/proxy.pid")
    if opts.node_tooling == "local":
        lines.append(".ralph/node-tools/")
    if opts.ignore_reports:
        lines.append(".ralph/TEST_REPORT.md")
        lines.append(".ralph/REVIEW_REPORT.md")
        lines.append(".ralph/FINAL.md")
        lines.append(".ralph/DONE")
        lines.append(".ralph/HUMAN_REQUEST.md")
        lines.append(".ralph/HUMAN_RESPONSE.md")
    if opts.ignore_venvs:
        lines.append(".venv/")
        lines.append("venv/")
    if opts.playwright:
        lines.append("playwright-report/")
        lines.append("test-results/")
        lines.append(".playwright/")
        lines.append("*.trace.zip")
    lines.append("")
    lines.append(MANAGED_END)
    return "\n".join(lines) + "\n"

def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")

def sync_gitignore(repo: Path, opts: GitignoreOptions) -> Path:
    repo = repo.resolve()
    gi = repo / ".gitignore"
    existing = _read_text(gi)
    block = render_managed_block(opts)

    if MANAGED_START in existing and MANAGED_END in existing:
        pre = existing.split(MANAGED_START, 1)[0]
        post = existing.split(MANAGED_END, 1)[1]
        if pre and not pre.endswith("\n"):
            pre += "\n"
        if post and not post.startswith("\n"):
            post = "\n" + post
        new_text = pre + block + post.lstrip("\n")
    else:
        new_text = existing
        if new_text:
            new_text = new_text.rstrip("\n") + "\n\n"
        new_text += block

    gi.write_text(new_text, encoding="utf-8")
    return gi

def managed_block_is_current(repo: Path, opts: GitignoreOptions) -> bool:
    repo = repo.resolve()
    gi = repo / ".gitignore"
    text = _read_text(gi)
    if MANAGED_START not in text or MANAGED_END not in text:
        return False
    start = text.find(MANAGED_START)
    end = text.find(MANAGED_END)
    if start == -1 or end == -1:
        return False
    end += len(MANAGED_END)
    current = text[start:end].strip() + "\n"
    expected = render_managed_block(opts).strip() + "\n"
    return current == expected
