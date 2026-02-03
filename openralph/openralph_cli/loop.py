from __future__ import annotations
from pathlib import Path
import os
import subprocess
import re
from typing import Iterable

from .settings import OpenRalphSettings
from .paths import Paths
from .opencode_manager import ensure_opencode
from .memory import query_memory, index_repo
from .git_manager import (
    is_git_repo,
    ensure_branch,
    checkpoint_commit,
    rollback_to_checkpoint,
    rollback_to_ref,
    is_worktree_dirty,
    worktree_status,
    write_diff_snapshot,
    update_last_green,
    head_sha,
)
from .logging import get_logger
from .features import get_feature_context
from .prd import (
    PRD_QA_QUESTIONS,
    generate_prd,
    generate_prd_from_answers,
    load_prd_answers,
    run_prd_qa,
    save_prd_answers,
    generate_prd_answers,
)

def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40] or "work"

def _read_text(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""

def _resolve_repo_path(repo: Path, value: str, default: Path) -> Path:
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else repo / p

def _prompt_path(repo: Path, path: Path) -> str:
    try:
        if path.is_relative_to(repo):
            return str(path.relative_to(repo))
    except Exception:
        pass
    return str(path)

def _parse_gate(report_text: str) -> bool | None:
    m = re.search(r"Gate:\s*(PASS|FAIL)", report_text, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).upper() == "PASS"

def _memory_hits_to_text(hits: Iterable, max_chars: int) -> str:
    parts: list[str] = []
    total = 0
    for h in hits:
        chunk = f"- {h.path}#{h.chunk_index} (score={h.score:.3f})\n{h.content[:800]}"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk) + 2
    return "\n\n".join(parts)

def _write_human_request(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")

def _clear_human_exchange(request_path: Path, response_path: Path) -> None:
    if request_path.exists():
        request_path.unlink()
    if response_path.exists():
        response_path.unlink()

def _build_prd_handoff_prompt() -> str:
    lines = [
        "# PRD Q&A",
        "",
        "Please answer the following questions in JSON with keys matching the question ids.",
        "Example:",
        '{"project_name": "My Project", "problem": "..."}',
        "",
        "Questions:",
    ]
    for key, question in PRD_QA_QUESTIONS:
        lines.append(f"- {key}: {question}")
    return "\n".join(lines)

def _extract_json_from_response(text: str) -> dict[str, str] | None:
    try:
        import json
        return json.loads(text)
    except Exception:
        return None

def _git_context(repo: Path, max_chars: int = 4000) -> str:
    if not is_git_repo(repo):
        return "No git context available."
    parts: list[str] = []
    try:
        stat = subprocess.run(["git", "diff", "--stat"], cwd=str(repo), text=True, capture_output=True)
        if stat.stdout.strip():
            parts.append("Diff --stat:\n" + stat.stdout.strip())
    except Exception:
        pass
    try:
        diff = subprocess.run(["git", "diff"], cwd=str(repo), text=True, capture_output=True)
        if diff.stdout.strip():
            parts.append("Diff:\n" + diff.stdout.strip())
    except Exception:
        pass
    ctx = "\n\n".join(parts) if parts else "No diff available."
    return ctx[:max_chars]

def run_loop(repo: Path, prompt: str, *, max_iters: int, settings: OpenRalphSettings | None = None) -> None:
    log = get_logger("loop")
    repo = repo.resolve()
    settings = settings or OpenRalphSettings.load(repo)
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
        if is_worktree_dirty(repo):
            log.warning("Git worktree has uncommitted changes before loop start")
            status = worktree_status(repo)
            if status:
                log.debug("Worktree status:\n%s", status)
        branch_name = _slugify(prompt)
        log.info("Ensuring git branch: %s", branch_name)
        ensure_branch(repo, branch_name)

    oc = ensure_opencode(repo, auto_install=settings.opencode_auto_install, version=settings.opencode_version)
    log.info("Using OpenCode: %s", oc.path)
    env = os.environ.copy()
    env.setdefault("OPENCODE_EXPERIMENTAL", "true")
    env.setdefault("OPENCODE_EXPERIMENTAL_LSP_TOOL", "true")

    test_report = _resolve_repo_path(repo, settings.loop_test_report, paths.test_report)
    review_report = _resolve_repo_path(repo, settings.loop_review_report, paths.review_report)
    final_report = _resolve_repo_path(repo, settings.loop_final_report, paths.final_report)

    if paths.done_marker.exists():
        last_test = _read_text(test_report)
        gate = _parse_gate(last_test)
        if gate:
            log.info("DONE marker present with PASS gate; stopping loop")
            return
        log.warning("DONE marker present but gate not PASS; ignoring and removing DONE")
        try:
            paths.done_marker.unlink()
        except Exception:
            pass

    # Ensure PRD exists before loop
    if not paths.prd.exists():
        mode = settings.loop_prd_qa_mode
        log.info("PRD missing; running PRD Q&A mode: %s", mode)
        if mode == "interactive":
            answers = run_prd_qa(repo)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
        elif mode == "handoff":
            if not paths.human_response.exists():
                _write_human_request(paths.human_request, _build_prd_handoff_prompt())
                log.warning("Wrote PRD questions to HUMAN_REQUEST; awaiting response")
                return
            data = _extract_json_from_response(_read_text(paths.human_response, max_chars=20000))
            if not data:
                log.warning("HUMAN_RESPONSE did not contain valid JSON for PRD answers")
                return
            save_prd_answers(repo, data)
            generate_prd_from_answers(repo, data, paths.prd)
            _clear_human_exchange(paths.human_request, paths.human_response)
        elif mode == "auto-then-handoff":
            answers = generate_prd_answers(repo, oc.path)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
            _write_human_request(paths.human_request, "Please review the generated PRD and list any changes.")
            log.warning("PRD drafted; awaiting review via HUMAN_REQUEST")
            return
        elif mode == "auto":
            answers = generate_prd_answers(repo, oc.path)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
        else:
            log.warning("Unknown PRD QA mode: %s", mode)

    gate_fails = 0
    for i in range(1, max_iters + 1):
        log.info("=== Iteration %d/%d ===", i, max_iters)
        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Awaiting HUMAN_RESPONSE before continuing")
            return

        # PRD refresh cadence
        if settings.loop_prd_refresh_every > 0 and i % settings.loop_prd_refresh_every == 0:
            log.info("PRD refresh triggered on iteration %d", i)
            if settings.loop_prd_refresh_mode == "ask":
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, "Provide PRD deltas or confirm no changes needed.")
                    log.warning("PRD refresh awaiting HUMAN_RESPONSE")
                    return
                updates = _read_text(paths.human_response, max_chars=20000)
                _clear_human_exchange(paths.human_request, paths.human_response)
                try:
                    generate_prd(repo, paths.prd, oc.path, extra_context=updates)
                except Exception as e:
                    log.warning("PRD refresh failed: %s", e, exc_info=True)
            else:
                try:
                    generate_prd(repo, paths.prd, oc.path)
                except Exception as e:
                    log.warning("PRD refresh failed: %s", e, exc_info=True)

        mem = ""
        try:
            log.debug("Querying memory with prompt (k=%d)", settings.memory_k)
            hits = query_memory(
                paths.memory_db,
                settings.ollama_host,
                settings.embed_model,
                prompt,
                k=settings.memory_k,
                path_boosts=[("docs/PRD.md", 1.3), ("docs/features/", 1.2)],
            )
            if hits:
                log.debug("Memory query returned %d hits", len(hits))
                mem = _memory_hits_to_text(hits, settings.memory_inject_max_chars)
            else:
                log.debug("Memory query returned no hits")
        except Exception as e:
            log.warning("Memory query failed (continuing): %s", e, exc_info=True)

        combined = prompt
        if mem:
            combined += "\n\n# Retrieved project memory (top hits)\n" + mem
        feature_ctx = get_feature_context(repo)
        if feature_ctx:
            combined += "\n\n# Current feature context\n" + feature_ctx
        if test_report.exists():
            combined += "\n\n# Prior Test Report\n" + _read_text(test_report, max_chars=8000)
        if review_report.exists():
            combined += "\n\n# Prior Review Report\n" + _read_text(review_report, max_chars=8000)
        if paths.human_response.exists():
            combined += "\n\n# Human Response\n" + _read_text(paths.human_response, max_chars=8000)
            _clear_human_exchange(paths.human_request, paths.human_response)
        final_rel = _prompt_path(repo, final_report)
        combined += (
            "\n\nRules:\n"
            "- Address test failures first.\n"
            "- Keep PRD and feature specs aligned.\n"
            "- If you need a decision, write to .ralph/HUMAN_REQUEST.md and stop.\n"
            f"- When complete: write {final_rel} and create .ralph/DONE."
        )

        builder_log = paths.logs / f"builder-iter-{i}.log"
        log.debug("Running OpenCode builder: %s", oc.path)
        p = subprocess.run([str(oc.path), "run", combined], cwd=str(repo), env=env, text=True, capture_output=True)
        builder_log.write_text((p.stdout or "") + "\n" + (p.stderr or ""), encoding="utf-8")
        log.debug("Builder output written to: %s", builder_log)
        if p.returncode != 0:
            log.warning("Builder stage exited with non-zero return code: %d", p.returncode)
        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Builder requested human input; stopping loop")
            return

        # Test stage
        git_ctx = _git_context(repo)
        test_prompt = (
            "You are the Testing Agent.\n\n"
            "Repo rules:\n"
            "- Prefer running fast checks first.\n"
            "- If you run commands, keep them minimal and relevant.\n"
            "- If dependencies are missing, say what's needed and propose the smallest install steps.\n\n"
            "Write a markdown report to the file: {report_path}\n"
            "It must include a line: Gate: PASS or Gate: FAIL.\n\n"
            "Include sections:\n"
            "# Test Report\n"
            "## Commands run\n"
            "## Results\n"
            "## Failures (if any)\n"
            "## Recommended next actions\n\n"
            "Recent changes:\n"
            "{git_ctx}\n\n"
            "Test policy (if present):\n"
            "{test_policy}\n"
        ).format(
            report_path=_prompt_path(repo, test_report),
            git_ctx=git_ctx,
            test_policy=_read_text(repo / ".ralph" / "test-policy.md", max_chars=4000) or "No test policy found.",
        )
        test_log = paths.logs / f"test-iter-{i}.log"
        p_test = subprocess.run([str(oc.path), "run", test_prompt], cwd=str(repo), env=env, text=True, capture_output=True)
        test_log.write_text((p_test.stdout or "") + "\n" + (p_test.stderr or ""), encoding="utf-8")
        log.debug("Test output written to: %s", test_log)
        if p_test.returncode != 0:
            log.warning("Test stage exited with non-zero return code: %d", p_test.returncode)
        if not test_report.exists() and (p_test.stdout or "").strip():
            test_report.parent.mkdir(parents=True, exist_ok=True)
            test_report.write_text(p_test.stdout, encoding="utf-8")

        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Test agent requested human input; stopping loop")
            return

        # Review stage
        prd_excerpt = _read_text(paths.prd, max_chars=4000) if paths.prd.exists() else "No PRD found."
        review_prompt = (
            "You are the Product/Review Agent.\n\n"
            "Your job:\n"
            "- Check alignment with docs/PRD.md and current feature specs.\n"
            "- Identify UX/product gaps, missing acceptance criteria, and edge cases.\n"
            "- Suggest improvements in plain language.\n\n"
            "Context:\n"
            "PRD (excerpt):\n"
            "{prd}\n\n"
            "Feature context:\n"
            "{feature}\n\n"
            "Test report (if present):\n"
            "{test_report}\n\n"
            "Recent changes:\n"
            "{git_ctx}\n\n"
            "Write a markdown report to the file: {report_path}\n"
            "Include sections:\n"
            "# Review Report\n"
            "## PRD alignment\n"
            "## User-impact / UX notes\n"
            "## Risks / edge cases\n"
            "## Acceptance criteria checklist\n"
            "## Questions (if any)\n\n"
            "If a decision is required, write .ralph/HUMAN_REQUEST.md and stop.\n"
        ).format(
            prd=prd_excerpt,
            feature=feature_ctx or "No current feature set.",
            test_report=_read_text(test_report, max_chars=4000) if test_report.exists() else "No test report found.",
            git_ctx=git_ctx,
            report_path=_prompt_path(repo, review_report),
        )
        review_log = paths.logs / f"review-iter-{i}.log"
        p_review = subprocess.run([str(oc.path), "run", review_prompt], cwd=str(repo), env=env, text=True, capture_output=True)
        review_log.write_text((p_review.stdout or "") + "\n" + (p_review.stderr or ""), encoding="utf-8")
        log.debug("Review output written to: %s", review_log)
        if p_review.returncode != 0:
            log.warning("Review stage exited with non-zero return code: %d", p_review.returncode)
        if not review_report.exists() and (p_review.stdout or "").strip():
            review_report.parent.mkdir(parents=True, exist_ok=True)
            review_report.write_text(p_review.stdout, encoding="utf-8")

        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Review agent requested human input; stopping loop")
            return

        gate_report = _read_text(test_report, max_chars=8000)
        gate = _parse_gate(gate_report)
        gates_ok = bool(gate)
        log.info("Iteration %d: test gate=%s", i, gate)
        if gates_ok:
            gate_fails = 0
            if is_git_repo(repo):
                try:
                    log.info("Creating checkpoint commit for iteration %d", i)
                    sha = checkpoint_commit(repo, f"openralph: checkpoint - iter {i}")
                    if not sha:
                        sha = head_sha(repo)
                    if sha:
                        update_last_green(repo, sha, paths.last_green)
                except Exception as e:
                    log.warning("Checkpoint commit failed: %s", e, exc_info=True)
            if paths.done_marker.exists():
                log.info("DONE marker found with PASS gate; stopping loop")
                break
            log.info("Gate PASS but no DONE marker; continuing loop")
        else:
            gate_fails += 1
            log.warning("Gate failed (count=%d/%d)", gate_fails, settings.loop_max_gate_fails)
            if p.stderr:
                log.debug("OpenCode stderr: %s", p.stderr[:500])
            if is_git_repo(repo):
                diff_path = paths.logs / f"gate-fail-iter-{i}.diff"
                write_diff_snapshot(repo, diff_path)
            if settings.loop_rollback_on_gate_fail and is_git_repo(repo) and gate_fails >= settings.loop_max_gate_fails:
                log.info("Rolling back after %d gate failures", gate_fails)
                if paths.last_green.exists():
                    rollback_to_ref(repo, paths.last_green.read_text(encoding="utf-8").strip())
                else:
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
