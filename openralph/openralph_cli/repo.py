from __future__ import annotations

from pathlib import Path
import re
import subprocess

def is_git_url(s: str) -> bool:
    return bool(re.match(r"^(https?://|git@).+|.+\.git$", s))

def ensure_repo(repo: str) -> Path:
    """
    If repo is a path: ensure it exists.
    If repo looks like a git URL: clone into a folder in cwd named after the repo.
    """
    p = Path(repo)
    if p.exists():
        return p.resolve()

    if is_git_url(repo):
        name = repo.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        dest = Path.cwd() / name
        if dest.exists():
            return dest.resolve()
        subprocess.run(["git", "clone", repo, str(dest)], check=True)
        return dest.resolve()

    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()
