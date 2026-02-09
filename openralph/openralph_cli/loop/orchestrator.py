from __future__ import annotations

from pathlib import Path
import socket

from ..features import set_current_feature
from ..git_manager import (
    ensure_branch,
    is_git_repo,
    is_worktree_dirty,
    worktree_status,
)
from ..logging import get_logger
from ..paths import Paths
from ..planner import generate_feature_queue, load_feature_queue, prd_changed
from ..prd import generate_prd_from_answers, run_prd_qa, save_prd_answers
from ..settings import OpenRalphSettings
from ..stack import StackChoice, detect_stack, read_stack_file, write_stack_file
from ..ui import Dashboard, notice, run_summary
from .agent_runner import _ensure_proxy, _run_native_agent
from .feature_runner import _kill_playwright_sessions, _reindex, _run_feature_iterations, _run_feature_queue
from .gate import _parse_gate
from .status import RunOutcome, write_run_artifacts
from .helpers import (
    _clear_human_exchange,
    _extract_json_from_response,
    _read_text,
    _resolve_repo_path,
    _slugify,
    _validate_prd_answers,
    _write_human_request,
)
from .prd_flow import _build_prd_handoff_prompt, _clear_prd_handoff_if_present, _generate_prd_answers_native
from ..prompts import STACK_SYSTEM


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

    signals = "\n".join(f"- {c.name}: {', '.join(c.signals)}" for c in choices) or "No stack signals detected."
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
        agent_role="code",
    )
    existing = read_stack_file(paths.stack)
    if existing:
        return existing

    fallback = StackChoice(name="unknown", reason="No stack detected", signals=[])
    write_stack_file(paths.stack, fallback)
    return fallback.name


def _preflight_backend(settings: OpenRalphSettings) -> tuple[bool, str]:
    host = settings.proxy_target_host
    port = settings.proxy_target_port
    try:
        with socket.create_connection((host, port), timeout=2):
            return True, f"{host}:{port} reachable"
    except OSError as e:
        return False, f"{host}:{port} unreachable ({e})"


def _gate_is_pass(repo: Path, paths: Paths, settings: OpenRalphSettings) -> bool:
    test_report = _resolve_repo_path(repo, settings.loop_test_report, paths.test_report)
    last_test = _read_text(test_report)
    gate = _parse_gate(last_test)
    return bool(gate)


def run_loop(
    repo: Path,
    prompt: str,
    *,
    max_iters: int,
    settings: OpenRalphSettings | None = None,
    mode: str = "standard",
) -> RunOutcome:
    log = get_logger("loop")
    repo = repo.resolve()
    settings = settings or OpenRalphSettings.load(repo)
    paths = Paths.for_repo(repo)
    paths.logs.mkdir(parents=True, exist_ok=True)
    outcome = RunOutcome(status="failed", reason="unknown", stage="startup")
    outcome.max_tool_errors = settings.loop_max_tool_errors
    is_fast_mode = mode == "fast"
    dashboard: Dashboard | None = None

    log.info("Starting run loop: repo=%s, max_iters=%d, auto_mode=%s", repo, max_iters, settings.loop_auto_mode or "(off)")
    notice(f"Run started (auto={settings.loop_auto_mode or 'off'}, max_iters={max_iters})", level="info")
    log.debug("Settings: ollama_host=%s, embed_model=%s", settings.ollama_host, settings.embed_model)

    def _finalize_outcome() -> None:
        if dashboard is not None:
            outcome.tool_errors = int(dashboard.state.tool_errors)
        try:
            outcome.gate_pass = _gate_is_pass(repo, paths, settings)
        except Exception:
            pass

        if settings.loop_auto_mode == "full" and outcome.stage == "feature_queue":
            queue = load_feature_queue(paths)
            if queue and queue.items:
                total = len(queue.items)
                done_count = sum(1 for it in queue.items if it.status == "done")
                failed_count = sum(1 for it in queue.items if it.status == "failed")
                outcome.total_features = total
                outcome.completed_features = done_count
                outcome.failed_features = failed_count
                if done_count < total and paths.done_marker.exists():
                    try:
                        paths.done_marker.unlink()
                    except OSError:
                        pass
                if done_count == total and total > 0 and outcome.gate_pass and not paths.done_marker.exists():
                    try:
                        paths.done_marker.write_text("auto\n", encoding="utf-8")
                    except OSError:
                        pass
                if done_count == total and total > 0 and outcome.gate_pass and paths.done_marker.exists():
                    outcome.status = "success"
                    outcome.reason = "all_features_completed"
                elif done_count < total:
                    if done_count > 0:
                        outcome.status = "partial"
                        outcome.reason = "feature_queue_incomplete"
                    elif failed_count > 0:
                        outcome.status = "failed"
                        outcome.reason = "feature_queue_failed"

        if (
            outcome.status == "success"
            and outcome.tool_errors > settings.loop_max_tool_errors
        ):
            outcome.status = "success_with_warnings"
            outcome.reason = (
                f"tool_errors_exceeded_threshold "
                f"({outcome.tool_errors}>{settings.loop_max_tool_errors})"
            )

        outcome.done_marker = paths.done_marker.exists()
        write_run_artifacts(
            paths.run_status,
            paths.run_summary,
            outcome=outcome,
            prompt=prompt,
            auto_mode=settings.loop_auto_mode,
        )

    if not settings.agent_native:
        log.error("agent.native is false, but OpenCode support has been removed.")
        outcome.status = "failed"
        outcome.reason = "agent_native_disabled"
        outcome.stage = "startup"
        _finalize_outcome()
        return outcome

    log.info("Using native agent (proxy port %d)", settings.proxy_listen_port)
    _ensure_proxy(settings, log)
    backend_ok, backend_detail = _preflight_backend(settings)
    if not backend_ok:
        log.error("Backend preflight failed: %s", backend_detail)
        outcome.status = "blocked"
        outcome.reason = f"backend_unreachable: {backend_detail}"
        outcome.stage = "preflight"
        _finalize_outcome()
        return outcome

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
            outcome.status = "success"
            outcome.reason = "done_marker_with_pass_gate"
            outcome.stage = "startup"
            outcome.done_marker = True
            outcome.gate_pass = True
            _finalize_outcome()
            return outcome
        log.warning("DONE marker present but gate not PASS; ignoring and removing DONE")
        try:
            paths.done_marker.unlink()
        except OSError:
            pass

    if settings.loop_prd_qa_mode in ("auto", "auto-then-handoff"):
        _clear_prd_handoff_if_present(paths)

    if (not is_fast_mode) and (not paths.prd.exists()):
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
                outcome.status = "blocked"
                outcome.reason = "human_input_required_prd_handoff"
                outcome.stage = "prd"
                _finalize_outcome()
                return outcome
            data = _extract_json_from_response(_read_text(paths.human_response, max_chars=20000))
            if not data:
                log.warning("HUMAN_RESPONSE did not contain valid JSON for PRD answers")
                outcome.status = "blocked"
                outcome.reason = "invalid_human_prd_response"
                outcome.stage = "prd"
                _finalize_outcome()
                return outcome
            save_prd_answers(repo, data)
            generate_prd_from_answers(repo, data, paths.prd)
            _clear_human_exchange(paths.human_request, paths.human_response)
        elif mode == "auto-then-handoff":
            answers = _generate_prd_answers_native(repo, settings, paths, log, user_prompt=prompt)
            if not _validate_prd_answers(answers):
                log.warning("Native auto PRD answers failed; falling back to handoff")
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, _build_prd_handoff_prompt())
                outcome.status = "blocked"
                outcome.reason = "auto_prd_failed_fallback_to_handoff"
                outcome.stage = "prd"
                _finalize_outcome()
                return outcome
            _clear_prd_handoff_if_present(paths)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
            _write_human_request(paths.human_request, "Please review the generated PRD and list any changes.")
            log.warning("PRD drafted; awaiting review via HUMAN_REQUEST")
            outcome.status = "blocked"
            outcome.reason = "human_input_required_prd_review"
            outcome.stage = "prd"
            _finalize_outcome()
            return outcome
        elif mode == "auto":
            answers = _generate_prd_answers_native(repo, settings, paths, log, user_prompt=prompt)
            if not _validate_prd_answers(answers):
                log.warning("Native auto PRD answers failed; falling back to handoff")
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, _build_prd_handoff_prompt())
                outcome.status = "blocked"
                outcome.reason = "auto_prd_failed_fallback_to_handoff"
                outcome.stage = "prd"
                _finalize_outcome()
                return outcome
            _clear_prd_handoff_if_present(paths)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
        else:
            log.warning("Unknown PRD QA mode: %s", mode)

    if paths.human_request.exists() and not paths.human_response.exists():
        log.info("Clearing stale HUMAN_REQUEST.md from prior run")
        _clear_human_exchange(paths.human_request, paths.human_response)

    if settings.ui_dashboard:
        dashboard = Dashboard()
        dashboard.start()

    try:
        if is_fast_mode:
            notice("Fast mode: skipping PRD/planner and building minimal runnable output first", level="info")
            outcome.stage = "run"
            fast_prompt = (
                prompt
                + "\n\nFAST MODE:\n"
                + "- Prioritize a minimal runnable/playable implementation.\n"
                + "- Minimize planning overhead; implement directly.\n"
                + "- Keep changes small and finish quickly.\n"
            )
            success = _run_feature_iterations(
                repo=repo,
                prompt=fast_prompt,
                max_iters=min(max_iters, 3),
                settings=settings,
                paths=paths,
                log=log,
                dashboard=dashboard,
            )
            outcome.stage = "run"
            outcome.done_marker = paths.done_marker.exists()
            outcome.gate_pass = _gate_is_pass(repo, paths, settings)
            if success and outcome.done_marker and outcome.gate_pass:
                outcome.status = "success"
                outcome.reason = "fast_mode_completed"
            else:
                outcome.status = "partial"
                outcome.reason = "fast_mode_incomplete"
            return outcome

        if settings.loop_auto_mode == "full":
            log.info("Auto-full mode: decomposing PRD into features")
            notice("Auto-full mode: generating plan and executing feature queue", level="info")
            outcome.stage = "planning"
            queue = load_feature_queue(paths)
            if queue is None or prd_changed(paths, queue):
                log.info("Running planner agent to decompose PRD into features")
                try:
                    queue = generate_feature_queue(repo, settings, paths, log)
                except Exception as e:
                    log.error("Planner failed: %s", e)
                    outcome.status = "failed"
                    outcome.reason = f"planner_failed: {e}"
                    outcome.stage = "planning"
                    return outcome
            outcome.stage = "feature_queue"
            queue_stats = _run_feature_queue(
                repo=repo,
                prompt=prompt,
                settings=settings,
                paths=paths,
                log=log,
                dashboard=dashboard,
            )
            outcome.stage = "feature_queue"
            outcome.total_features = int(queue_stats["total"])
            outcome.completed_features = int(queue_stats["done"])
            outcome.failed_features = int(queue_stats["failed"])
            outcome.done_marker = paths.done_marker.exists()
            outcome.gate_pass = _gate_is_pass(repo, paths, settings)
            if bool(queue_stats["completed_all"]) and outcome.done_marker and outcome.gate_pass:
                outcome.status = "success"
                outcome.reason = "all_features_completed"
            elif outcome.completed_features > 0:
                outcome.status = "partial"
                outcome.reason = "feature_queue_incomplete"
            else:
                outcome.status = "failed"
                outcome.reason = "feature_queue_failed"
            return outcome

        outcome.stage = "run"
        success = _run_feature_iterations(
            repo=repo,
            prompt=prompt,
            max_iters=max_iters,
            settings=settings,
            paths=paths,
            log=log,
            dashboard=dashboard,
        )
        outcome.stage = "run"
        outcome.done_marker = paths.done_marker.exists()
        outcome.gate_pass = _gate_is_pass(repo, paths, settings)
        if not success:
            log.warning("Run loop completed without achieving DONE+PASS")
            outcome.status = "partial"
            outcome.reason = "iterations_exhausted_without_done"
        elif outcome.done_marker and outcome.gate_pass:
            outcome.status = "success"
            outcome.reason = "completed_with_done_and_gate"
        else:
            outcome.status = "partial"
            outcome.reason = "completed_without_done_or_gate"
        return outcome
    except KeyboardInterrupt:
        log.warning("Run interrupted by user")
        if outcome.status == "failed" and outcome.reason == "unknown":
            outcome.status = "partial"
        if not outcome.reason or outcome.reason == "unknown":
            outcome.reason = "interrupted"
        if not outcome.stage or outcome.stage == "startup":
            outcome.stage = "run"
        return outcome
    except Exception as e:
        log.error("Run loop crashed: %s", e, exc_info=True)
        outcome.status = "failed"
        outcome.reason = f"unexpected_error: {e}"
        if not outcome.stage:
            outcome.stage = "run"
        return outcome
    finally:
        _kill_playwright_sessions(repo, log)
        if dashboard is not None:
            dashboard.stop()
            run_summary(dashboard.state)
        _finalize_outcome()
