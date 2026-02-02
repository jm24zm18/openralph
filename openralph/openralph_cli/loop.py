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
from .logging import get_logger

def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40] or "work"

def run_loop(repo: Path, prompt: str, *, max_iters: int) -> None:
    log = get_logger("loop")
    repo = repo.resolve()
    settings = OpenRalphSettings.load(repo)
    paths = Paths.for_repo(repo)
    paths.logs.mkdir(parents=True, exist_ok=True)

    log.info("Starting run loop: repo=%s, max_iters=%d", repo, max_iters)
    log.debug("Settings: ollama_host=%s, embed_model=%s", settings.ollama_host, settings.embed_model)

    # best-effort index at start
    try:
        log.debug("Indexing repository at start")
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
        log.debug("Initial indexing complete")
    except Exception as e:
        log.warning("Initial memory indexing failed (continuing): %s", e, exc_info=True)

    if is_git_repo(repo):
        branch_name = _slugify(prompt)
        log.info("Ensuring git branch: %s", branch_name)
        ensure_branch(repo, branch_name)

    oc = ensure_opencode(repo, auto_install=settings.opencode_auto_install, version=settings.opencode_version)
    log.info("Using OpenCode: %s", oc.path)
    env = os.environ.copy()
    env.setdefault("OPENCODE_EXPERIMENTAL", "true")
    env.setdefault("OPENCODE_EXPERIMENTAL_LSP_TOOL", "true")

    gate_fails = 0
    for i in range(1, max_iters + 1):
        log.info("=== Iteration %d/%d ===", i, max_iters)
        mem = ""
        try:
            log.debug("Querying memory with prompt (k=%d)", settings.memory_k)
            hits = query_memory(paths.memory_db, settings.ollama_host, settings.embed_model, prompt, k=settings.memory_k)
            if hits:
                log.debug("Memory query returned %d hits", len(hits))
                mem = "\n\n".join(
                    [f"- {h.path}#{h.chunk_index} (score={h.score:.3f})\n{h.content[:800]}" for h in hits]
                )
            else:
                log.debug("Memory query returned no hits")
        except Exception as e:
            log.warning("Memory query failed (continuing): %s", e, exc_info=True)

        combined = prompt
        if mem:
            combined += "\n\n# Retrieved project memory (top hits)\n" + mem

        iter_log = paths.logs / f"iter-{i}.log"
        log.debug("Running OpenCode: %s", oc.path)
        p = subprocess.run([str(oc.path), "run", combined], cwd=str(repo), env=env, text=True, capture_output=True)
        iter_log.write_text((p.stdout or "") + "\n" + (p.stderr or ""), encoding="utf-8")
        log.debug("OpenCode output written to: %s", iter_log)

        gates_ok = (p.returncode == 0)
        log.info("Iteration %d: returncode=%d, gates_ok=%s", i, p.returncode, gates_ok)
        if gates_ok:
            gate_fails = 0
            if is_git_repo(repo):
                try:
                    log.info("Creating checkpoint commit for iteration %d", i)
                    checkpoint_commit(repo, f"openralph: checkpoint - iter {i}")
                except Exception as e:
                    log.warning("Checkpoint commit failed: %s", e, exc_info=True)
            log.info("Run loop succeeded on iteration %d", i)
            break
        else:
            gate_fails += 1
            log.warning("Gate failed (count=%d/%d)", gate_fails, settings.loop_max_gate_fails)
            if p.stderr:
                log.debug("OpenCode stderr: %s", p.stderr[:500])
            if settings.loop_rollback_on_gate_fail and is_git_repo(repo) and gate_fails >= settings.loop_max_gate_fails:
                log.info("Rolling back to checkpoint after %d gate failures", gate_fails)
                rollback_to_checkpoint(repo)
                gate_fails = 0

        # best-effort reindex
        try:
            log.debug("Re-indexing repository after iteration %d", i)
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
        except Exception as e:
            log.warning("Re-indexing failed (continuing): %s", e, exc_info=True)
    else:
        log.warning("Run loop exhausted max_iters=%d without success", max_iters)
