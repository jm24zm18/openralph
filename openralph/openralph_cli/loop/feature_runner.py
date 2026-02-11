from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..agent.browser import close_session as close_browser_session
from ..features import get_feature_context, set_current_feature
from ..git_manager import (
    checkpoint_commit,
    is_git_repo,
    rollback_to_checkpoint,
    rollback_to_ref,
    update_last_green,
    write_diff_snapshot,
    head_sha,
)
from ..issues import (
    extract_issues_from_review_report,
    extract_issues_from_test_report,
    format_open_issues_for_prompt,
    load_issues,
    save_issues,
    upsert_issues,
)
from ..memory import index_repo, query_memory
from ..paths import Paths
from ..planner import (
    FeatureQueueItem,
    load_feature_queue,
    mark_feature_status,
    save_feature_queue,
)
from ..prompts import BUILDER_SYSTEM, REVIEW_SYSTEM, TEST_SYSTEM, build_builder_prompt, build_review_prompt, build_test_prompt
from ..settings import OpenRalphSettings
from ..stack import default_test_command, read_stack_file
from ..ui import Dashboard, notice
from .agent_runner import _git_context, _run_native_agent, _run_stack_default_tests
from .gate import _find_forbidden_test_installs, _find_missing_test_imports, _parse_gate, _run_smoke_checks
from .helpers import (
    _clear_human_exchange,
    _memory_chunk_count,
    _memory_hits_to_text,
    _prompt_path,
    _read_text,
    _resolve_repo_path,
)


def _derive_goal_contract(prompt: str) -> str:
    lowered = prompt.lower()
    if "game" in lowered and ("playable" in lowered or "browser game" in lowered):
        return (
            "- The game can be started and played via browser controls.\n"
            "- Core game loop exists (start, active play, terminal state).\n"
            "- Scoring is visible and updates during play.\n"
            "- A restart or replay path exists after terminal state.\n"
        )
    return ""


def _missing_goal_evidence(goal_contract: str, *evidence_texts: str) -> list[str]:
    if not goal_contract.strip():
        return []

    combined = "\n".join(evidence_texts).lower()
    checks = [
        ("playable controls", ("play", "control", "input")),
        ("core gameplay loop", ("loop", "start", "game over")),
        ("visible scoring", ("score",)),
        ("restart/replay path", ("restart", "replay")),
    ]
    missing: list[str] = []
    for label, patterns in checks:
        if not any(token in combined for token in patterns):
            missing.append(label)
    return missing


def _kill_playwright_sessions(repo: Path, log) -> None:
    try:
        close_browser_session()
    except Exception:
        pass
    pw_cli = shutil.which("playwright-cli")
    if not pw_cli:
        local = repo / ".ralph" / "node-tools" / "node_modules" / ".bin" / "playwright-cli"
        if local.exists():
            pw_cli = str(local)
    if not pw_cli:
        return
    try:
        subprocess.run([pw_cli, "kill-all"], capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        pass  # best-effort


def _strip_questions_section_from_review(text: str) -> tuple[str, bool]:
    if "## Questions" not in text:
        return text, False

    lines = text.splitlines()
    cleaned: list[str] = []
    skipping = False
    changed = False
    for line in lines:
        if line.startswith("## "):
            if line.strip().lower().startswith("## questions"):
                skipping = True
                changed = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            cleaned.append(line)

    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    cleaned.extend([
        "",
        "## Open assumptions (auto mode)",
        "- Reviewer questions were auto-cleared in auto mode; proceed with explicit assumptions.",
    ])
    return "\n".join(cleaned) + "\n", changed


def _reindex(repo: Path, paths: Paths, settings: OpenRalphSettings, log, label: str = "") -> None:
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


def _runtime_env_with_node(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    path_entries: list[str] = []
    local_bin = repo / ".ralph" / "node-tools" / "node_modules" / ".bin"
    if local_bin.is_dir():
        path_entries.append(str(local_bin))
    home = Path.home()
    nvm_versions = home / ".nvm" / "versions" / "node"
    if nvm_versions.is_dir():
        candidates = sorted(nvm_versions.glob("v*/bin"), reverse=True)
        for candidate in candidates:
            if candidate.is_dir():
                path_entries.append(str(candidate))
                break
    existing = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    env["PATH"] = os.pathsep.join(path_entries + [p for p in existing if p not in path_entries])
    return env


def _node_runtime_unavailable(repo: Path) -> str | None:
    env = _runtime_env_with_node(repo)
    try:
        node_ok = subprocess.run(
            ["bash", "-lc", "command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1"],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"node/npm availability check failed: {e}"
    if node_ok.returncode == 0:
        return None
    return "node/npm not available in runtime PATH for test stage"


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
    enforce_goal_contract: bool = True,
    dashboard: Dashboard | None = None,
) -> bool:
    test_report = _resolve_repo_path(repo, settings.loop_test_report, paths.test_report)
    review_report = _resolve_repo_path(repo, settings.loop_review_report, paths.review_report)
    final_report = _resolve_repo_path(repo, settings.loop_final_report, paths.final_report)
    final_rel = _prompt_path(repo, final_report)

    all_issues = load_issues(paths)
    gate_fails = 0
    goal_contract = _derive_goal_contract(prompt)
    for i in range(1, max_iters + 1):
        if i == 1:
            chunk_count = _memory_chunk_count(paths.memory_db)
            if chunk_count == 0:
                log.info("Memory index is empty at iteration start; running bootstrap re-index")
                _reindex(repo, paths, settings, log, "bootstrap-empty-memory")

        label = f"{iter_label_prefix}iter {i}/{max_iters}" if iter_label_prefix else f"Iteration {i}/{max_iters}"
        log.info("=== %s ===", label)
        notice(f"{label}: builder", level="info")
        if dashboard is not None:
            dashboard.set_iteration(i, max_iters)
        if feature_slug:
            log.info("Coordinator: feature=%s stage=builder", feature_slug)

        if queue_item is not None:
            queue_item.iterations_used = i

        if paths.human_request.exists() and not paths.human_response.exists():
            if settings.loop_auto_mode:
                log.info("Clearing stale HUMAN_REQUEST (auto mode)")
                if dashboard is not None:
                    dashboard.add_event("warn", "human", "clearing stale HUMAN_REQUEST in auto mode")
                _clear_human_exchange(paths.human_request, paths.human_response)
            else:
                log.warning("Awaiting HUMAN_RESPONSE before continuing")
                if dashboard is not None:
                    dashboard.add_event("warn", "human", "awaiting HUMAN_RESPONSE")
                return False

        if settings.loop_prd_refresh_every > 0 and i % settings.loop_prd_refresh_every == 0:
            log.info("PRD refresh triggered on iteration %d", i)
            from ..prd import generate_prd

            if settings.loop_prd_refresh_mode == "ask":
                if not paths.human_response.exists():
                    from .helpers import _write_human_request

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
            goal_contract=goal_contract,
            auto_mode=bool(settings.loop_auto_mode),
        )

        if dashboard is not None:
            dashboard.set_stage("builder")
        builder_log = paths.logs / f"builder-iter-{i}.log"
        builder_system = BUILDER_SYSTEM.replace("FINAL_PATH", final_rel)
        builder_output = ""
        log.debug("Running native builder agent")
        builder_output, _builder_stats = _run_native_agent(
            prompt=combined,
            repo=repo,
            settings=settings,
            log_file=builder_log,
            log=log,
            system_prompt=builder_system,
            agent_role="code",
            dashboard=dashboard,
        )
        log.debug("Builder output written to: %s", builder_log)
        if paths.human_request.exists() and not paths.human_response.exists():
            if settings.loop_auto_mode:
                log.info("Builder requested human input; clearing in auto mode")
                if dashboard is not None:
                    dashboard.add_event("warn", "builder", "requested human input (auto-cleared)")
                _clear_human_exchange(paths.human_request, paths.human_response)
            else:
                log.warning("Builder requested human input; stopping iterations")
                if dashboard is not None:
                    dashboard.add_event("warn", "builder", "requested human input; stopping")
                return False

        if dashboard is not None:
            dashboard.set_stage("test")
        notice(f"{label}: test", level="info")
        if feature_slug:
            log.info("Coordinator: feature=%s stage=test", feature_slug)
        git_ctx = _git_context(repo)
        test_report_iter = test_report.parent / f"TEST_REPORT.iter-{i}.md"
        stack_ctx = _read_text(paths.stack, max_chars=4000)
        test_policy_text = _read_text(repo / ".ralph" / "test-policy.md", max_chars=4000)
        pretest_missing = _find_missing_test_imports(repo)
        if pretest_missing:
            log.warning("Pre-test import check failed (missing modules): %s", ", ".join(pretest_missing))
            if dashboard is not None:
                dashboard.add_event("warn", "test", f"missing modules: {', '.join(pretest_missing)}")
        test_prompt = build_test_prompt(
            report_path=_prompt_path(repo, test_report_iter),
            git_ctx=git_ctx,
            test_policy=test_policy_text or "No test policy found.",
            stack_context=stack_ctx,
            goal_contract=goal_contract,
        )
        test_log = paths.logs / f"test-iter-{i}.log"
        test_output = ""
        ran_fallback = False
        fallback_ok = False
        test_stats = {"tool_errors": 0, "bash_success": 0}
        stack_name = read_stack_file(paths.stack) or ""
        if stack_name == "node":
            runtime_error = _node_runtime_unavailable(repo)
            if runtime_error:
                log.warning("Node runtime preflight failed: %s", runtime_error)
                note = (
                    "# Test Report\n\n"
                    "## Commands run\n"
                    "- (preflight only)\n\n"
                    "## Results\n"
                    "Node.js runtime preflight failed before executing tests.\n\n"
                    "## Failures\n"
                    f"- {runtime_error}\n\n"
                    "## Recommended next actions\n"
                    "- Ensure node and npm are available in the runtime PATH used by agent bash tools.\n\n"
                    "Gate: FAIL\n"
                )
                test_report_iter.parent.mkdir(parents=True, exist_ok=True)
                test_report_iter.write_text(note, encoding="utf-8")
                test_report.parent.mkdir(parents=True, exist_ok=True)
                test_report.write_text(note, encoding="utf-8")
                ran_fallback = True
                fallback_ok = False
        if (not ran_fallback) and (not test_policy_text.strip()):
            cmd = default_test_command(stack_name, repo)
            if cmd:
                log.debug("Running stack default tests: %s", cmd)
                report_text, _ok = _run_stack_default_tests(repo, cmd)
                fallback_ok = _ok
                test_report_iter.parent.mkdir(parents=True, exist_ok=True)
                test_report_iter.write_text(report_text, encoding="utf-8")
                test_report.parent.mkdir(parents=True, exist_ok=True)
                test_report.write_text(report_text, encoding="utf-8")
                ran_fallback = True

        if not ran_fallback:
            log.debug("Running native test agent")
            test_output, test_stats = _run_native_agent(
                prompt=test_prompt,
                repo=repo,
                settings=settings,
                log_file=test_log,
                log=log,
                system_prompt=TEST_SYSTEM,
                agent_role="test",
                dashboard=dashboard,
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
            if settings.loop_auto_mode:
                log.info("Test agent requested human input; clearing in auto mode")
                if dashboard is not None:
                    dashboard.add_event("warn", "test", "requested human input (auto-cleared)")
                _clear_human_exchange(paths.human_request, paths.human_response)
            else:
                log.warning("Test agent requested human input; stopping iterations")
                if dashboard is not None:
                    dashboard.add_event("warn", "test", "requested human input; stopping")
                return False

        test_report_text = _read_text(test_report_iter, max_chars=8000)
        new_test_issues = extract_issues_from_test_report(test_report_text, i, feature_slug)
        if new_test_issues:
            log.debug("Extracted %d issues from test report", len(new_test_issues))
            all_issues = upsert_issues(all_issues, new_test_issues, iteration=i)
            save_issues(paths, all_issues)

        if dashboard is not None:
            dashboard.set_stage("review")
        notice(f"{label}: review", level="info")
        if feature_slug:
            log.info("Coordinator: feature=%s stage=review", feature_slug)
        prd_excerpt = _read_text(paths.prd, max_chars=4000) if paths.prd.exists() else "No PRD found."
        review_prompt = build_review_prompt(
            prd_excerpt=prd_excerpt,
            feature_context=feature_ctx or "No current feature set.",
            test_report=_read_text(test_report_iter, max_chars=4000) if test_report_iter.exists() else "No test report found.",
            git_ctx=git_ctx,
            report_path=_prompt_path(repo, review_report),
            goal_contract=goal_contract,
            auto_mode=bool(settings.loop_auto_mode),
        )
        review_log = paths.logs / f"review-iter-{i}.log"
        review_output = ""
        log.debug("Running native review agent")
        review_output, _review_stats = _run_native_agent(
            prompt=review_prompt,
            repo=repo,
            settings=settings,
            log_file=review_log,
            log=log,
            system_prompt=REVIEW_SYSTEM,
            agent_role="review",
            dashboard=dashboard,
        )
        log.debug("Review output written to: %s", review_log)
        if not review_report.exists() and review_output.strip():
            review_report.parent.mkdir(parents=True, exist_ok=True)
            review_report.write_text(review_output, encoding="utf-8")
        if settings.loop_auto_mode and review_report.exists():
            existing_review = review_report.read_text(encoding="utf-8", errors="replace")
            sanitized, changed = _strip_questions_section_from_review(existing_review)
            if changed:
                review_report.write_text(sanitized, encoding="utf-8")
                log.info("Removed review questions section in auto mode")
                if dashboard is not None:
                    dashboard.add_event("warn", "review", "questions section removed (auto mode)")

        if paths.human_request.exists() and not paths.human_response.exists():
            if settings.loop_auto_mode:
                log.info("Review agent requested human input; clearing in auto mode")
                if dashboard is not None:
                    dashboard.add_event("warn", "review", "requested human input (auto-cleared)")
                _clear_human_exchange(paths.human_request, paths.human_response)
            else:
                log.warning("Review agent requested human input; stopping iterations")
                if dashboard is not None:
                    dashboard.add_event("warn", "review", "requested human input; stopping")
                return False

        review_text = _read_text(review_report, max_chars=8000)
        new_review_issues = extract_issues_from_review_report(review_text, i, feature_slug)
        if new_review_issues:
            log.debug("Extracted %d issues from review report", len(new_review_issues))
            all_issues = upsert_issues(all_issues, new_review_issues, iteration=i)
            save_issues(paths, all_issues)

        if dashboard is not None:
            dashboard.set_stage("gate")
        notice(f"{label}: gate", level="info")
        last_bash_exit = test_stats.get("last_bash_exit")
        pytest_collected = test_stats.get("pytest_collected")
        if ran_fallback:
            last_bash_exit = 0 if fallback_ok else 1
        tests_ran = last_bash_exit == 0
        if pytest_collected == 0:
            tests_ran = False
        gate_report = _read_text(test_report_iter, max_chars=8000)
        gate = _parse_gate(gate_report)
        if gate is None and test_output.strip():
            log.debug("Gate report had no result; falling back to raw test output")
            gate = _parse_gate(test_output)
        forbidden_installs = _find_forbidden_test_installs(repo)
        if gate and (not tests_ran or pretest_missing):
            missing_line = ""
            if pretest_missing:
                missing_line = "Missing modules: " + ", ".join(pretest_missing) + "\n"
            note = (
                "# Test Report\n\n"
                "## Results\n"
                "Tests did not run successfully or required modules were missing.\n\n"
                f"{missing_line}\n"
                "## Failures\n"
                "- Tests did not run successfully, so this gate cannot pass.\n\n"
                "Gate: FAIL\n"
            )
            test_report_iter.write_text(note, encoding="utf-8")
            test_report.write_text(note, encoding="utf-8")
            gate = False
        if gate and forbidden_installs:
            log.warning("Forbidden install commands found in tests: %s", "; ".join(forbidden_installs[:3]))
            note = (
                "# Test Report\n\n"
                "## Results\n"
                "Tests include forbidden environment-mutating install commands.\n\n"
                "## Failures\n"
                + "".join(f"- {f}\n" for f in forbidden_installs)
                + "\nGate: FAIL\n"
            )
            test_report_iter.write_text(note, encoding="utf-8")
            test_report.write_text(note, encoding="utf-8")
            gate = False
        if gate and settings.loop_smoke_check:
            stack_name = read_stack_file(paths.stack) or ""
            smoke_failures = _run_smoke_checks(repo, stack_name, timeout=settings.loop_smoke_timeout)
            if smoke_failures:
                log.warning("Smoke check FAILED — overriding gate to FAIL: %s", "; ".join(smoke_failures))
                if dashboard is not None:
                    dashboard.add_event("error", "smoke", f"smoke check failed: {'; '.join(smoke_failures[:3])}")
                note = (
                    "# Test Report\n\n"
                    "## Results\n"
                    "Tests passed but runtime smoke check failed.\n\n"
                    "## Smoke Check Failures\n"
                    + "".join(f"- {f}\n" for f in smoke_failures)
                    + "\nGate: FAIL\n"
                )
                test_report_iter.write_text(note, encoding="utf-8")
                test_report.write_text(note, encoding="utf-8")
                gate = False
            else:
                log.info("Smoke check passed")
                if dashboard is not None:
                    dashboard.add_event("success", "smoke", "smoke check passed")
        if gate and goal_contract and enforce_goal_contract:
            final_text = _read_text(final_report, max_chars=8000) if final_report.exists() else ""
            missing_goal_evidence = _missing_goal_evidence(goal_contract, gate_report, review_text, final_text)
            if missing_goal_evidence:
                log.warning("Goal evidence check failed: %s", "; ".join(missing_goal_evidence))
                note = (
                    "# Test Report\n\n"
                    "## Results\n"
                    "Prompt-level acceptance checks are not yet evidenced.\n\n"
                    "## Missing evidence\n"
                    + "".join(f"- {item}\n" for item in missing_goal_evidence)
                    + "\nGate: FAIL\n"
                )
                test_report_iter.write_text(note, encoding="utf-8")
                test_report.write_text(note, encoding="utf-8")
                gate = False
        gates_ok = bool(gate)
        log.info("%s: test gate=%s", label, gate)
        if dashboard is not None:
            dashboard.record_gate(i, gates_ok)
        if gates_ok:
            if dashboard is not None:
                dashboard.add_event("success", "gate", f"{label}: PASS")
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
            if settings.loop_auto_mode == "full":
                try:
                    paths.done_marker.write_text("auto\n", encoding="utf-8")
                    log.info("Auto-full mode: created DONE marker after PASS gate; feature complete")
                    return True
                except OSError as e:
                    log.warning("Failed to auto-create DONE marker in auto-full mode: %s", e)
            final_text = _read_text(paths.final_report, max_chars=8000).strip()
            if final_text and settings.loop_auto_mode != "full":
                try:
                    paths.done_marker.write_text("auto\n", encoding="utf-8")
                    log.info("Auto-created DONE marker after PASS gate (FINAL.md present); feature complete")
                    return True
                except OSError as e:
                    log.warning("Failed to auto-create DONE marker: %s", e)
            log.info("Gate PASS but no DONE marker; continuing iterations")
        else:
            if dashboard is not None:
                dashboard.add_event("error", "gate", f"{label}: FAIL")
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
                log.warning(
                    "Stopping: %d consecutive gate failures (max=%d)",
                    gate_fails,
                    settings.loop_max_gate_fails,
                )
                return False

        _reindex(repo, paths, settings, log, f"after iter {i}")
    else:
        log.warning("Exhausted max_iters=%d without success", max_iters)

    return False


def _run_feature_queue(
    repo: Path,
    prompt: str,
    settings: OpenRalphSettings,
    paths: Paths,
    log,
    dashboard: Dashboard | None = None,
) -> dict[str, int | bool]:
    queue = load_feature_queue(paths)
    if not queue or not queue.items:
        log.warning("Feature queue is empty; nothing to process")
        return {
            "total": 0,
            "done": 0,
            "failed": 0,
            "completed_all": False,
        }

    total = len(queue.items)
    for idx, item in enumerate(queue.items, 1):
        if item.status == "done":
            log.info("Feature %d/%d [%s]: already done, skipping", idx, total, item.slug)
            continue
        if item.status == "failed" and not settings.loop_retry_failed:
            log.info("Feature %d/%d [%s]: failed, retry disabled, skipping", idx, total, item.slug)
            continue

        log.info("=== Feature %d/%d: %s ===", idx, total, item.title)
        notice(f"Feature {idx}/{total}: {item.title}", level="info")
        if dashboard is not None:
            dashboard.set_feature(idx, total, item.slug)

        feature_path = repo / item.feature_path
        if feature_path.exists():
            set_current_feature(repo, feature_path)
        else:
            log.warning("Feature path %s does not exist; skipping", item.feature_path)
            mark_feature_status(queue, item.slug, "failed")
            save_feature_queue(paths, queue)
            continue

        if paths.done_marker.exists():
            try:
                paths.done_marker.unlink()
            except OSError:
                pass
        _clear_human_exchange(paths.human_request, paths.human_response)

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

        os.environ["PLAYWRIGHT_CLI_SESSION"] = f"openralph-{item.slug}"

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
            enforce_goal_contract=(idx == total),
            dashboard=dashboard,
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
        _reindex(repo, paths, settings, log, f"after feature {item.slug}")
        _kill_playwright_sessions(repo, log)

    done_count = sum(1 for it in queue.items if it.status == "done")
    failed_count = sum(1 for it in queue.items if it.status == "failed")
    log.info("Feature queue complete: %d done, %d failed, %d total", done_count, failed_count, total)

    if done_count == total:
        log.info("All features completed successfully")
    return {
        "total": total,
        "done": done_count,
        "failed": failed_count,
        "completed_all": done_count == total,
    }
