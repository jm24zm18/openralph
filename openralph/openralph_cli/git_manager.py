from __future__ import annotations
from pathlib import Path
import subprocess

def _run(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(repo), text=True, capture_output=True)

def is_git_repo(repo: Path) -> bool:
    p = _run(repo, ["git", "rev-parse", "--is-inside-work-tree"])
    return p.returncode == 0 and p.stdout.strip() == "true"

def current_branch(repo: Path) -> str:
    p = _run(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return p.stdout.strip() if p.returncode == 0 else ""

def ensure_branch(repo: Path, slug: str, prefix: str = "openralph/") -> str:
    name = f"{prefix}{slug}"
    cur = current_branch(repo)
    if cur == name:
        return name
    p = _run(repo, ["git", "show-ref", "--verify", f"refs/heads/{name}"])
    if p.returncode != 0:
        p2 = _run(repo, ["git", "checkout", "-b", name])
        if p2.returncode != 0:
            raise RuntimeError(p2.stderr.strip() or p2.stdout.strip())
    else:
        p2 = _run(repo, ["git", "checkout", name])
        if p2.returncode != 0:
            raise RuntimeError(p2.stderr.strip() or p2.stdout.strip())
    return name

def checkpoint_commit(repo: Path, message: str) -> str:
    _run(repo, ["git", "add", "-A"])
    p = _run(repo, ["git", "commit", "-m", message])
    if p.returncode != 0 and "nothing to commit" in (p.stdout + p.stderr).lower():
        return ""
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    p2 = _run(repo, ["git", "rev-parse", "HEAD"])
    return p2.stdout.strip()

def latest_checkpoint(repo: Path, prefix: str = "openralph: checkpoint") -> str | None:
    p = _run(repo, ["git", "log", "--pretty=%H:%s", "-n", "50"])
    if p.returncode != 0:
        return None
    for line in p.stdout.splitlines():
        if ":" not in line:
            continue
        sha, subj = line.split(":", 1)
        if subj.strip().startswith(prefix):
            return sha.strip()
    return None

def rollback_to_checkpoint(repo: Path) -> str:
    sha = latest_checkpoint(repo)
    if not sha:
        raise RuntimeError("No openralph checkpoint commit found.")
    p = _run(repo, ["git", "reset", "--hard", sha])
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return sha
