from __future__ import annotations
from pathlib import Path
import subprocess

from .logging import get_logger


def _run(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    log = get_logger("git")
    log.debug("Running git command: %s", " ".join(args))
    result = subprocess.run(args, cwd=str(repo), text=True, capture_output=True)
    if result.returncode != 0:
        log.debug("Git command failed (rc=%d): %s", result.returncode, result.stderr.strip()[:200])
    return result

def is_git_repo(repo: Path) -> bool:
    p = _run(repo, ["git", "rev-parse", "--is-inside-work-tree"])
    return p.returncode == 0 and p.stdout.strip() == "true"

def current_branch(repo: Path) -> str:
    p = _run(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return p.stdout.strip() if p.returncode == 0 else ""

def ensure_branch(repo: Path, slug: str, prefix: str = "openralph/") -> str:
    log = get_logger("git")
    name = f"{prefix}{slug}"
    cur = current_branch(repo)
    if cur == name:
        log.debug("Already on branch: %s", name)
        return name
    p = _run(repo, ["git", "show-ref", "--verify", f"refs/heads/{name}"])
    if p.returncode != 0:
        log.info("Creating new branch: %s", name)
        p2 = _run(repo, ["git", "checkout", "-b", name])
        if p2.returncode != 0:
            log.error("Failed to create branch %s: %s", name, p2.stderr.strip())
            raise RuntimeError(p2.stderr.strip() or p2.stdout.strip())
    else:
        log.info("Checking out existing branch: %s", name)
        p2 = _run(repo, ["git", "checkout", name])
        if p2.returncode != 0:
            log.error("Failed to checkout branch %s: %s", name, p2.stderr.strip())
            raise RuntimeError(p2.stderr.strip() or p2.stdout.strip())
    return name

def checkpoint_commit(repo: Path, message: str) -> str:
    log = get_logger("git")
    log.debug("Creating checkpoint commit: %s", message)
    _run(repo, ["git", "add", "-A"])
    p = _run(repo, ["git", "commit", "-m", message])
    if p.returncode != 0 and "nothing to commit" in (p.stdout + p.stderr).lower():
        log.debug("Nothing to commit")
        return ""
    if p.returncode != 0:
        log.error("Commit failed: %s", p.stderr.strip())
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    p2 = _run(repo, ["git", "rev-parse", "HEAD"])
    sha = p2.stdout.strip()
    log.info("Checkpoint commit created: %s", sha[:8])
    return sha

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
    log = get_logger("git")
    sha = latest_checkpoint(repo)
    if not sha:
        log.error("No checkpoint commit found for rollback")
        raise RuntimeError("No openralph checkpoint commit found.")
    log.info("Rolling back to checkpoint: %s", sha[:8])
    p = _run(repo, ["git", "reset", "--hard", sha])
    if p.returncode != 0:
        log.error("Rollback failed: %s", p.stderr.strip())
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    log.info("Rollback complete")
    return sha
