from __future__ import annotations
from pathlib import Path
import os
import subprocess
import re

from .settings import OpenRalphSettings
from .paths import Paths
from .opencode_manager import ensure_opencode
from .memory import query_memory, index_repo
from .git_manager import is_git_repo, ensure_branch, checkpoint_commit, rollback_to_checkpoint

def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40] or "work"

def run_loop(repo: Path, prompt: str, *, max_iters: int) -> None:
    repo = repo.resolve()
    settings = OpenRalphSettings.load(repo)
    paths = Paths.for_repo(repo)
    paths.logs.mkdir(parents=True, exist_ok=True)

    # best-effort index at start
    try:
        index_repo(
            repo,
            paths.memory_db,
            settings.ollama_host,
            settings.embed_model,
            include_exts=set(settings.memory_include_exts),
            exclude_dirs=set(settings.memory_exclude_dirs),
            chunk_chars=settings.memory_chunk_chars,
            chunk_overlap=settings.memory_chunk_overlap,
        )
    except Exception:
        pass

    if is_git_repo(repo):
        ensure_branch(repo, _slugify(prompt))

    oc = ensure_opencode(repo, auto_install=settings.opencode_auto_install, version=settings.opencode_version)
    env = os.environ.copy()
    env.setdefault("OPENCODE_EXPERIMENTAL", "true")
    env.setdefault("OPENCODE_EXPERIMENTAL_LSP_TOOL", "true")

    gate_fails = 0
    for i in range(1, max_iters + 1):
        mem = ""
        try:
            hits = query_memory(paths.memory_db, settings.ollama_host, settings.embed_model, prompt, k=settings.memory_k)
            if hits:
                mem = "\n\n".join(
                    [f"- {h.path}#{h.chunk_index} (score={h.score:.3f})\n{h.content[:800]}" for h in hits]
                )
        except Exception:
            pass

        combined = prompt
        if mem:
            combined += "\n\n# Retrieved project memory (top hits)\n" + mem

        log = paths.logs / f"iter-{i}.log"
        p = subprocess.run([str(oc.path), "run", combined], cwd=str(repo), env=env, text=True, capture_output=True)
        log.write_text((p.stdout or "") + "\n" + (p.stderr or ""), encoding="utf-8")

        gates_ok = (p.returncode == 0)
        if gates_ok:
            gate_fails = 0
            if is_git_repo(repo):
                try:
                    checkpoint_commit(repo, f"openralph: checkpoint - iter {i}")
                except Exception:
                    pass
            break
        else:
            gate_fails += 1
            if settings.loop_rollback_on_gate_fail and is_git_repo(repo) and gate_fails >= settings.loop_max_gate_fails:
                rollback_to_checkpoint(repo)
                gate_fails = 0

        # best-effort reindex
        try:
            index_repo(
                repo,
                paths.memory_db,
                settings.ollama_host,
                settings.embed_model,
                include_exts=set(settings.memory_include_exts),
                exclude_dirs=set(settings.memory_exclude_dirs),
                chunk_chars=settings.memory_chunk_chars,
                chunk_overlap=settings.memory_chunk_overlap,
            )
        except Exception:
            pass
