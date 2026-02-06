from __future__ import annotations
from pathlib import Path
import subprocess
import re
from typing import Iterable

from .settings import OpenRalphSettings
from .paths import Paths
from .memory import query_memory, index_repo
from .agent import run_agent, AgentConfig
from .agent.providers import OpenAIProvider
from .proxy import ProxyConfig, ProxyServer, proxy_is_listening
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
from .features import get_feature_context, set_current_feature
from .prd import (
    PRD_QA_QUESTIONS,
    generate_prd,
    generate_prd_from_answers,
    run_prd_qa,
    save_prd_answers,
    build_prd_answers_prompt,
)
from .prompts import (
    BUILDER_SYSTEM,
    TEST_SYSTEM,
    REVIEW_SYSTEM,
    STACK_SYSTEM,
    build_builder_prompt,
    build_test_prompt,
    build_review_prompt,
)
from .planner import (
    FeatureQueueItem,
    load_feature_queue,
    save_feature_queue,
    mark_feature_status,
    prd_changed,
    generate_feature_queue,
)
from .issues import (
    load_issues,
    save_issues,
    extract_issues_from_test_report,
    extract_issues_from_review_report,
    format_open_issues_for_prompt,
)
from .stack import detect_stack, read_stack_file, write_stack_file, default_test_command, StackChoice


# ── Helpers (unchanged) ─────────────────────────────────────────────────

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
    pattern = re.compile(
        r"^\s*(?:#+\s*)?Gate\s*[:\-]\s*(PASS|FAIL)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(report_text)
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
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                import json
                return json.loads(text[start:end + 1])
            except Exception:
                return None
        return None


def _validate_prd_answers(data: dict[str, str] | None) -> bool:
    if not data or not isinstance(data, dict):
        return False
    expected_keys = {key for key, _ in PRD_QA_QUESTIONS}
    if not expected_keys.issubset(set(data.keys())):
        return False
    for key in expected_keys:
        value = data.get(key)
        if not isinstance(value, str):
            return False
    return True


def _clear_prd_handoff_if_present(paths: Paths) -> None:
    if not paths.human_request.exists():
        return
    try:
        content = _read_text(paths.human_request, max_chars=2000)
    except Exception:
        return
    if "# PRD Q&A" in content:
        _clear_human_exchange(paths.human_request, paths.human_response)


def _generate_prd_answers_native(repo: Path, settings: OpenRalphSettings, paths: Paths, log, user_prompt: str = "") -> dict[str, str] | None:
    prompt = build_prd_answers_prompt(repo, user_prompt=user_prompt)
    log_file = paths.logs / "prd-qa-auto.log"
    result = run_agent(
        provider=_get_provider(settings),
        prompt=prompt,
        repo=repo,
        config=AgentConfig(
            max_turns=settings.agent_max_turns,
            system_prompt=(
                "You are a product manager. You may use tools if helpful, but your final response "
                "MUST be a single JSON object answering all questions. No markdown."
            ),
            timeout_default=settings.agent_timeout,
            max_output_chars=settings.agent_max_output,
        ),
    )
    output = result.final_text or ""
    log_content = (
        f"Prompt:\n{prompt}\n\n---\n\nOutput:\n{output}\n\n---\n\n"
        f"Tool calls: {result.tool_calls_made}\nCompleted: {result.completed}\n"
    )
    if result.error:
        log_content += f"Error: {result.error}\n"
    log_file.write_text(log_content, encoding="utf-8")
    return _extract_json_from_response(output.strip())

def _get_provider(settings: OpenRalphSettings) -> OpenAIProvider:
    """Create an OpenAI-compatible provider using proxy settings."""
    base_url = f"http://127.0.0.1:{settings.proxy_listen_port}"
    return OpenAIProvider(
        base_url=base_url,
        api_key=settings.proxy_api_key,
        model=settings.proxy_model_id,
        timeout=settings.agent_timeout,
    )


def _ensure_proxy(settings: OpenRalphSettings, log) -> None:
    """Ensure the proxy is running if enabled or required by native agent."""
    if not settings.proxy_enabled and not settings.proxy_auto_start:
        return

    if proxy_is_listening(settings.proxy_listen_port):
        log.debug("Proxy already listening on port %d", settings.proxy_listen_port)
        return

    log.info("Starting proxy on port %d", settings.proxy_listen_port)
    config = ProxyConfig(
        listen_port=settings.proxy_listen_port,
        target_host=settings.proxy_target_host,
        target_port=settings.proxy_target_port,
        target_model=settings.proxy_target_model,
    )
    server = ProxyServer(config)
    server.start(daemon=True)
    # Give the thread a moment to bind the port
    import time
    for _ in range(10):
        if proxy_is_listening(settings.proxy_listen_port):
            log.debug("Proxy is ready on port %d", settings.proxy_listen_port)
            break
        time.sleep(0.1)
    else:
        log.warning("Proxy may not be ready on port %d after 1s", settings.proxy_listen_port)


def _run_native_agent(
    prompt: str,
    repo: Path,
    settings: OpenRalphSettings,
    log_file: Path,
    log,
    system_prompt: str = "",
) -> str:
    """Run the native agent and return its final output."""
    provider = _get_provider(settings)
    config = AgentConfig(
        max_turns=settings.agent_max_turns,
        system_prompt=system_prompt,
        timeout_default=settings.agent_timeout,
        max_output_chars=settings.agent_max_output,
    )

    output_lines = []

    def on_text(text: str) -> None:
        output_lines.append(text)

    def on_tool_call(name: str, args: dict) -> None:
        log.debug("Tool call: %s", name)

    def on_tool_result(name: str, result: str, is_error: bool) -> None:
        status = "ERROR" if is_error else "OK"
        log.debug("Tool result [%s]: %s: %s", status, name, result[:100])

    result = run_agent(
        provider=provider,
        prompt=prompt,
        repo=repo,
        config=config,
        on_text=on_text,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
    )

    # Write log
    log_content = f"Prompt:\n{prompt[:2000]}\n\n---\n\nOutput:\n{result.final_text}\n\n---\n\nTool calls: {result.tool_calls_made}\nCompleted: {result.completed}\n"
    if result.error:
        log_content += f"Error: {result.error}\n"
    log_file.write_text(log_content, encoding="utf-8")

    return result.final_text


def _ensure_stack_choice(
    repo: Path,
    paths: Paths,
    settings: OpenRalphSettings,
    log,
    prompt: str,
) -> str:
    existing = read_stack_file(paths.stack)
    if existing:
        return existing

    choices = detect_stack(repo)
    if len(choices) == 1:
        write_stack_file(paths.stack, choices[0])
        return choices[0].name

    signals = "\n".join(
        f"- {c.name}: {', '.join(c.signals)}" for c in choices
    ) or "No stack signals detected."
    stack_prompt = (
        "Select a single primary tech stack for this repo.\n\n"
        f"User request:\n{prompt}\n\n"
        f"Detected signals:\n{signals}\n\n"
        "Write your decision to .ralph/STACK.md."
    )
    log.debug("Running stack selection agent")
    _run_native_agent(
        prompt=stack_prompt,
        repo=repo,
        settings=settings,
        log_file=paths.logs / "stack-selection.log",
        log=log,
        system_prompt=STACK_SYSTEM,
    )
    existing = read_stack_file(paths.stack)
    if existing:
        return existing

    fallback = StackChoice(name="unknown", reason="No stack detected", signals=[])
    write_stack_file(paths.stack, fallback)
    return fallback.name


def _run_stack_default_tests(repo: Path, cmd: str) -> tuple[str, bool]:
    proc = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    output = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    gate = "PASS" if proc.returncode == 0 else "FAIL"
    report = (
        "# Test Report\n\n"
        "## Commands run\n"
        f"- {cmd}\n\n"
        "## Results\n"
        f"{'Command succeeded.' if proc.returncode == 0 else 'Command failed.'}\n\n"
        "## Failures (if any)\n"
        f"{'(none)' if proc.returncode == 0 else 'See output below.'}\n\n"
        "## Recommended next actions\n"
        "- Fix failing tests or install missing dependencies.\n\n"
        "```\n"
        f"{output.strip()}\n"
        "```\n\n"
        f"Gate: {gate}\n"
    )
    return report, proc.returncode == 0


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


def _reindex(repo: Path, paths: Paths, settings: OpenRalphSettings, log, label: str = "") -> None:
    """Best-effort memory reindex."""
    try:
        log.debug("Re-indexing repository%s", f" ({label})" if label else "")
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


# ── Layer 3: Per-feature iterations ─────────────────────────────────────

def _run_feature_iterations(
    repo: Path,
    prompt: str,
    max_iters: int,
    settings: OpenRalphSettings,
    paths: Paths,
    log,
    feature_slug: str = "",
    iter_label_prefix: str = "",
    queue_item: FeatureQueueItem | None = None,
) -> bool:
    """
    Run build/test/review iterations for the current feature (or generic prompt).
    Returns True if DONE+PASS achieved.
    """
    test_report = _resolve_repo_path(repo, settings.loop_test_report, paths.test_report)
    review_report = _resolve_repo_path(repo, settings.loop_review_report, paths.review_report)
    final_report = _resolve_repo_path(repo, settings.loop_final_report, paths.final_report)
    final_rel = _prompt_path(repo, final_report)

    # Load existing issues for this feature
    all_issues = load_issues(paths)

    gate_fails = 0
    for i in range(1, max_iters + 1):
        label = f"{iter_label_prefix}iter {i}/{max_iters}" if iter_label_prefix else f"Iteration {i}/{max_iters}"
        log.info("=== %s ===", label)

        if queue_item is not None:
            queue_item.iterations_used = i

        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Awaiting HUMAN_RESPONSE before continuing")
            return False

        # PRD refresh cadence
        if settings.loop_prd_refresh_every > 0 and i % settings.loop_prd_refresh_every == 0:
            log.info("PRD refresh triggered on iteration %d", i)
            if settings.loop_prd_refresh_mode == "ask":
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, "Provide PRD deltas or confirm no changes needed.")
                    log.warning("PRD refresh awaiting HUMAN_RESPONSE")
                    return False
                updates = _read_text(paths.human_response, max_chars=20000)
                _clear_human_exchange(paths.human_request, paths.human_response)
                try:
                    generate_prd(repo, paths.prd, extra_context=updates)
                except Exception as e:
                    log.warning("PRD refresh failed: %s", e, exc_info=True)
            else:
                try:
                    generate_prd(repo, paths.prd)
                except Exception as e:
                    log.warning("PRD refresh failed: %s", e, exc_info=True)

        # Memory query
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

        # Build combined prompt
        feature_ctx = get_feature_context(repo) or ""
        stack_ctx = _read_text(paths.stack, max_chars=4000)
        open_issues_text = format_open_issues_for_prompt(all_issues, feature_slug)
        human_resp = ""
        if paths.human_response.exists():
            human_resp = _read_text(paths.human_response, max_chars=8000)
            _clear_human_exchange(paths.human_request, paths.human_response)

        combined = build_builder_prompt(
            user_prompt=prompt,
            memory_context=mem,
            feature_context=feature_ctx,
            stack_context=stack_ctx,
            test_report=_read_text(test_report, max_chars=8000) if test_report.exists() else "",
            review_report=_read_text(review_report, max_chars=8000) if review_report.exists() else "",
            human_response=human_resp,
            final_path=final_rel,
            open_issues=open_issues_text,
        )

        # ── Builder stage ───────────────────────────────────────────────
        builder_log = paths.logs / f"builder-iter-{i}.log"
        builder_system = BUILDER_SYSTEM.format(final_path=final_rel)
        builder_output = ""
        log.debug("Running native builder agent")
        builder_output = _run_native_agent(
            prompt=combined,
            repo=repo,
            settings=settings,
            log_file=builder_log,
            log=log,
            system_prompt=builder_system,
        )
        log.debug("Builder output written to: %s", builder_log)
        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Builder requested human input; stopping iterations")
            return False

        # ── Test stage ──────────────────────────────────────────────────
        git_ctx = _git_context(repo)
        test_report_iter = test_report.parent / f"TEST_REPORT.iter-{i}.md"
        stack_ctx = _read_text(paths.stack, max_chars=4000)
        test_policy_text = _read_text(repo / ".ralph" / "test-policy.md", max_chars=4000)
        test_prompt = build_test_prompt(
            report_path=_prompt_path(repo, test_report_iter),
            git_ctx=git_ctx,
            test_policy=test_policy_text or "No test policy found.",
            stack_context=stack_ctx,
        )
        test_log = paths.logs / f"test-iter-{i}.log"
        test_output = ""
        ran_fallback = False
        if not test_policy_text.strip():
            stack_name = read_stack_file(paths.stack) or ""
            cmd = default_test_command(stack_name, repo)
            if cmd:
                log.debug("Running stack default tests: %s", cmd)
                report_text, _ok = _run_stack_default_tests(repo, cmd)
                test_report_iter.parent.mkdir(parents=True, exist_ok=True)
                test_report_iter.write_text(report_text, encoding="utf-8")
                test_report.parent.mkdir(parents=True, exist_ok=True)
                test_report.write_text(report_text, encoding="utf-8")
                ran_fallback = True

        if not ran_fallback:
            log.debug("Running native test agent")
            test_output = _run_native_agent(
                prompt=test_prompt,
                repo=repo,
                settings=settings,
                log_file=test_log,
                log=log,
                system_prompt=TEST_SYSTEM,
            )
        log.debug("Test output written to: %s", test_log)
        if test_report_iter.exists():
            test_report.parent.mkdir(parents=True, exist_ok=True)
            test_report.write_text(test_report_iter.read_text(encoding="utf-8"), encoding="utf-8")
        elif test_output.strip():
            test_report.parent.mkdir(parents=True, exist_ok=True)
            test_report_iter.write_text(test_output, encoding="utf-8")
            test_report.write_text(test_output, encoding="utf-8")

        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Test agent requested human input; stopping iterations")
            return False

        # Extract issues from test report
        test_report_text = _read_text(test_report_iter, max_chars=8000)
        new_test_issues = extract_issues_from_test_report(test_report_text, i, feature_slug)
        if new_test_issues:
            log.debug("Extracted %d issues from test report", len(new_test_issues))
            # Merge (dedup by id)
            existing_ids = {iss.id for iss in all_issues}
            for ni in new_test_issues:
                if ni.id not in existing_ids:
                    all_issues.append(ni)
                    existing_ids.add(ni.id)
            save_issues(paths, all_issues)

        # ── Review stage ────────────────────────────────────────────────
        prd_excerpt = _read_text(paths.prd, max_chars=4000) if paths.prd.exists() else "No PRD found."
        review_prompt = build_review_prompt(
            prd_excerpt=prd_excerpt,
            feature_context=feature_ctx or "No current feature set.",
            test_report=_read_text(test_report_iter, max_chars=4000) if test_report_iter.exists() else "No test report found.",
            git_ctx=git_ctx,
            report_path=_prompt_path(repo, review_report),
        )
        review_log = paths.logs / f"review-iter-{i}.log"
        review_output = ""
        log.debug("Running native review agent")
        review_output = _run_native_agent(
            prompt=review_prompt,
            repo=repo,
            settings=settings,
            log_file=review_log,
            log=log,
            system_prompt=REVIEW_SYSTEM,
        )
        log.debug("Review output written to: %s", review_log)
        if not review_report.exists() and review_output.strip():
            review_report.parent.mkdir(parents=True, exist_ok=True)
            review_report.write_text(review_output, encoding="utf-8")

        if paths.human_request.exists() and not paths.human_response.exists():
            log.warning("Review agent requested human input; stopping iterations")
            return False

        # Extract issues from review report
        review_text = _read_text(review_report, max_chars=8000)
        new_review_issues = extract_issues_from_review_report(review_text, i, feature_slug)
        if new_review_issues:
            log.debug("Extracted %d issues from review report", len(new_review_issues))
            existing_ids = {iss.id for iss in all_issues}
            for ni in new_review_issues:
                if ni.id not in existing_ids:
                    all_issues.append(ni)
                    existing_ids.add(ni.id)
            save_issues(paths, all_issues)

        # ── Gate evaluation ─────────────────────────────────────────────
        gate_report = _read_text(test_report_iter, max_chars=8000)
        gate = _parse_gate(gate_report)
        if gate is None and test_output.strip():
            log.debug("Gate report had no result; falling back to raw test output")
            gate = _parse_gate(test_output)
        gates_ok = bool(gate)
        log.info("%s: test gate=%s", label, gate)
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
                log.info("DONE marker found with PASS gate; feature complete")
                return True
            log.info("Gate PASS but no DONE marker; continuing iterations")
        else:
            gate_fails += 1
            log.warning("Gate failed (count=%d/%d)", gate_fails, settings.loop_max_gate_fails)
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
            elif gate_fails >= settings.loop_max_gate_fails:
                log.warning("Stopping: %d consecutive gate failures (max=%d)",
                            gate_fails, settings.loop_max_gate_fails)
                return False

        # best-effort reindex
        _reindex(repo, paths, settings, log, f"after iter {i}")
    else:
        log.warning("Exhausted max_iters=%d without success", max_iters)

    return False


# ── Layer 2: Feature queue processing ───────────────────────────────────

def _run_feature_queue(
    repo: Path,
    prompt: str,
    settings: OpenRalphSettings,
    paths: Paths,
    log,
) -> None:
    """Iterate through the feature queue, running iterations per feature."""
    queue = load_feature_queue(paths)
    if not queue or not queue.items:
        log.warning("Feature queue is empty; nothing to process")
        return

    total = len(queue.items)
    for idx, item in enumerate(queue.items, 1):
        if item.status == "done":
            log.info("Feature %d/%d [%s]: already done, skipping", idx, total, item.slug)
            continue
        if item.status == "failed" and not settings.loop_retry_failed:
            log.info("Feature %d/%d [%s]: failed, retry disabled, skipping", idx, total, item.slug)
            continue

        log.info("=== Feature %d/%d: %s ===", idx, total, item.title)

        # Set current feature
        feature_path = repo / item.feature_path
        if feature_path.exists():
            set_current_feature(repo, feature_path)
        else:
            log.warning("Feature path %s does not exist; skipping", item.feature_path)
            mark_feature_status(queue, item.slug, "failed")
            save_feature_queue(paths, queue)
            continue

        # Reset per-feature markers
        if paths.done_marker.exists():
            try:
                paths.done_marker.unlink()
            except Exception:
                pass

        mark_feature_status(queue, item.slug, "in_progress")
        save_feature_queue(paths, queue)

        max_iters = item.max_iterations or settings.loop_max_feature_iters
        feature_prompt = (
            f"Implement the feature: {item.title}\n\n"
            f"Read the feature specifications in {item.feature_path}/ for requirements, "
            f"acceptance criteria, and test plan. Write runnable source code that satisfies "
            f"all acceptance criteria.\n\n"
            f"Project context (original request): {prompt}"
        )

        success = _run_feature_iterations(
            repo=repo,
            prompt=feature_prompt,
            max_iters=max_iters,
            settings=settings,
            paths=paths,
            log=log,
            feature_slug=item.slug,
            iter_label_prefix=f"[{item.slug}] ",
            queue_item=item,
        )

        if success:
            mark_feature_status(queue, item.slug, "done")
            log.info("Feature [%s] completed successfully", item.slug)
            if is_git_repo(repo):
                try:
                    checkpoint_commit(repo, f"openralph: feature done - {item.slug}")
                except Exception as e:
                    log.warning("Feature checkpoint commit failed: %s", e, exc_info=True)
        else:
            mark_feature_status(queue, item.slug, "failed")
            log.warning("Feature [%s] did not complete", item.slug)

        save_feature_queue(paths, queue)

        # Reindex between features
        _reindex(repo, paths, settings, log, f"after feature {item.slug}")

    # Summary
    done_count = sum(1 for it in queue.items if it.status == "done")
    failed_count = sum(1 for it in queue.items if it.status == "failed")
    log.info("Feature queue complete: %d done, %d failed, %d total", done_count, failed_count, total)

    if done_count == total:
        log.info("All features completed successfully")


# ── Layer 1: Main entry point ───────────────────────────────────────────

def run_loop(repo: Path, prompt: str, *, max_iters: int, settings: OpenRalphSettings | None = None) -> None:
    log = get_logger("loop")
    repo = repo.resolve()
    settings = settings or OpenRalphSettings.load(repo)
    paths = Paths.for_repo(repo)
    paths.logs.mkdir(parents=True, exist_ok=True)

    log.info("Starting run loop: repo=%s, max_iters=%d, auto_mode=%s", repo, max_iters, settings.loop_auto_mode or "(off)")
    log.debug("Settings: ollama_host=%s, embed_model=%s", settings.ollama_host, settings.embed_model)

    if not settings.agent_native:
        log.error("agent.native is false, but OpenCode support has been removed.")
        raise RuntimeError("agent.native must be true; OpenCode support has been removed.")

    log.info("Using native agent (proxy port %d)", settings.proxy_listen_port)
    _ensure_proxy(settings, log)

    # best-effort index at start
    _reindex(repo, paths, settings, log, "initial")
    _ensure_stack_choice(repo, paths, settings, log, prompt)

    if is_git_repo(repo):
        if is_worktree_dirty(repo):
            log.warning("Git worktree has uncommitted changes before loop start")
            status = worktree_status(repo)
            if status:
                log.debug("Worktree status:\n%s", status)
        branch_name = _slugify(prompt)
        log.info("Ensuring git branch: %s", branch_name)
        ensure_branch(repo, branch_name)
    else:
        log.warning(
            "Repository is NOT a git repo. Checkpoints, rollbacks, and "
            "diff context will be unavailable. Run 'git init' or 'openralph init' first."
        )

    test_report = _resolve_repo_path(repo, settings.loop_test_report, paths.test_report)

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

    # Clear stale PRD handoff if auto modes are enabled
    if settings.loop_prd_qa_mode in ("auto", "auto-then-handoff"):
        _clear_prd_handoff_if_present(paths)

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
            answers = _generate_prd_answers_native(repo, settings, paths, log, user_prompt=prompt)
            if not _validate_prd_answers(answers):
                log.warning("Native auto PRD answers failed; falling back to handoff")
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, _build_prd_handoff_prompt())
                return
            _clear_prd_handoff_if_present(paths)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
            _write_human_request(paths.human_request, "Please review the generated PRD and list any changes.")
            log.warning("PRD drafted; awaiting review via HUMAN_REQUEST")
            return
        elif mode == "auto":
            answers = _generate_prd_answers_native(repo, settings, paths, log, user_prompt=prompt)
            if not _validate_prd_answers(answers):
                log.warning("Native auto PRD answers failed; falling back to handoff")
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, _build_prd_handoff_prompt())
                return
            _clear_prd_handoff_if_present(paths)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
        else:
            log.warning("Unknown PRD QA mode: %s", mode)

    # Clear stale HUMAN_REQUEST from prior runs (e.g. leftover PRD handoff)
    # A fresh `run` invocation means the user is explicitly starting over,
    # so any unanswered request is stale.
    if paths.human_request.exists() and not paths.human_response.exists():
        log.info("Clearing stale HUMAN_REQUEST.md from prior run")
        _clear_human_exchange(paths.human_request, paths.human_response)

    # ── Auto-full mode: decompose PRD into features and process them ────
    if settings.loop_auto_mode == "full":
        log.info("Auto-full mode: decomposing PRD into features")

        queue = load_feature_queue(paths)
        if queue is None or prd_changed(paths, queue):
            log.info("Running planner agent to decompose PRD into features")
            queue = generate_feature_queue(repo, settings, paths, log)

        _run_feature_queue(
            repo=repo,
            prompt=prompt,
            settings=settings,
            paths=paths,
            log=log,
        )
        return

    # ── Default: flat iteration loop (existing behavior) ────────────────
    success = _run_feature_iterations(
        repo=repo,
        prompt=prompt,
        max_iters=max_iters,
        settings=settings,
        paths=paths,
        log=log,
    )
    if not success:
        log.warning("Run loop completed without achieving DONE+PASS")
