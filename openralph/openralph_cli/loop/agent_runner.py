from __future__ import annotations

from pathlib import Path
import re
import subprocess
import time

from ..agent import AgentConfig, run_agent
from ..agent.providers import OpenAIProvider
from ..proxy import ProxyConfig, ProxyServer, proxy_is_listening
from ..settings import OpenRalphSettings, get_provider_config
from ..stack import read_stack_file
from ..ui import Dashboard, _brief_tool_args, notice


def _get_provider(settings: OpenRalphSettings, role: str = "") -> OpenAIProvider:
    provider_cfg = get_provider_config(settings, role=role)
    return OpenAIProvider(
        base_url=str(provider_cfg["base_url"]),
        api_key=str(provider_cfg["api_key"]),
        model=str(provider_cfg["model"]),
        timeout=int(provider_cfg["timeout"]),
    )


def _ensure_proxy(settings: OpenRalphSettings, log) -> None:
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
        log_requests=settings.proxy_log_requests,
        cors_enabled=settings.proxy_cors_enabled,
        cors_allow_origin=settings.proxy_cors_allow_origin,
    )
    server = ProxyServer(config)
    server.start(daemon=True)

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
    agent_role: str = "code",
    dashboard: Dashboard | None = None,
) -> tuple[str, dict]:
    provider = _get_provider(settings, role=agent_role)
    permission_map = {
        "code": settings.agent_code_permissions,
        "plan": settings.agent_plan_permissions,
        "test": settings.agent_test_permissions,
        "review": settings.agent_review_permissions,
    }
    allowed_tools = set(permission_map.get(agent_role, settings.agent_code_permissions))
    stack_name = ""
    stack_path = repo / ".ralph" / "STACK.md"
    if stack_path.exists():
        stack_name = read_stack_file(stack_path) or ""
    effective_sandbox_mode = settings.sandbox_mode
    if stack_name == "node" and settings.sandbox_mode == "docker":
        log.info(
            "Keeping sandbox mode as docker for node stack (%s role) per strict containerized tool execution",
            agent_role,
        )

    config = AgentConfig(
        max_turns=settings.agent_max_turns,
        system_prompt=system_prompt,
        timeout_default=settings.agent_timeout,
        max_output_chars=settings.agent_max_output,
        allowed_tools=allowed_tools,
        sandbox_enabled=settings.sandbox_enabled,
        sandbox_mode=effective_sandbox_mode,
        sandbox_docker_image=settings.sandbox_docker_image,
        sandbox_network=settings.sandbox_network,
        sandbox_fail_closed=settings.sandbox_fail_closed,
        sandbox_env_allowlist=settings.sandbox_env_allowlist,
        browser_headless=settings.browser_headless,
        browser_viewport_width=settings.browser_viewport_width,
        browser_viewport_height=settings.browser_viewport_height,
        browser_default_timeout=settings.browser_default_timeout,
        browser_console_buffer_max=settings.browser_console_buffer_max,
        browser_network_buffer_max=settings.browser_network_buffer_max,
    )

    output_lines = []
    tool_errors = 0
    bash_success = 0
    last_bash_exit: int | None = None
    pytest_collected: int | None = None
    started_at = time.monotonic()
    last_heartbeat_at = started_at

    def _emit_heartbeat(last_tool: str) -> None:
        nonlocal last_heartbeat_at
        now = time.monotonic()
        if (now - last_heartbeat_at) < 15:
            return
        elapsed = int(now - started_at)
        mins, secs = divmod(elapsed, 60)
        elapsed_text = f"{mins:02d}:{secs:02d}" if mins else f"{secs}s"
        notice(
            f"Still working ({agent_role} stage, {elapsed_text} elapsed, last tool: {last_tool}).",
            level="info",
        )
        last_heartbeat_at = now

    def on_text(text: str) -> None:
        output_lines.append(text)

    def on_tool_call(name: str, args: dict) -> None:
        log.info("Agent tool: %s", name)
        _emit_heartbeat(name)
        if dashboard is not None:
            dashboard.add_tool_call(name, _brief_tool_args(name, args))

    def on_tool_result(name: str, result: str, is_error: bool) -> None:
        nonlocal tool_errors, bash_success, last_bash_exit, pytest_collected
        status = "ERROR" if is_error else "OK"
        log.debug("Tool result [%s]: %s: %s", status, name, result[:100])
        summary = ""
        if is_error:
            tool_errors += 1
        if name == "bash":
            m = re.search(r"\[exit code:\s*(-?\d+)\]", result)
            if m:
                try:
                    code = int(m.group(1))
                    last_bash_exit = code
                    if code == 0:
                        bash_success += 1
                    summary = f"[exit={code}]"
                except ValueError:
                    last_bash_exit = None
            if "no tests ran" in result:
                pytest_collected = 0
                summary = (summary + " no-tests").strip()
            m = re.search(r"collected\s+(\d+)\s+items?", result)
            if m:
                try:
                    pytest_collected = int(m.group(1))
                    summary = (summary + f" collected={pytest_collected}").strip()
                except ValueError:
                    pass
        if dashboard is not None:
            dashboard.add_tool_result(name=name, ok=not is_error, summary=summary)
        _emit_heartbeat(name)

    def on_turn(turn: int) -> None:
        _emit_heartbeat(f"turn-{turn}")
        if dashboard is not None:
            dashboard.set_turn(turn)

    result = run_agent(
        provider=provider,
        prompt=prompt,
        repo=repo,
        config=config,
        on_text=on_text,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        on_turn=on_turn,
    )

    log_content = (
        f"Prompt:\n{prompt[:2000]}\n\n---\n\nOutput:\n{result.final_text}\n\n---\n\n"
        f"Tool calls: {result.tool_calls_made}\nCompleted: {result.completed}\n"
    )
    if result.error:
        log_content += f"Error: {result.error}\n"
    log_file.write_text(log_content, encoding="utf-8")

    stats = {
        "tool_errors": tool_errors,
        "bash_success": bash_success,
        "last_bash_exit": last_bash_exit,
        "pytest_collected": pytest_collected,
    }
    return result.final_text, stats


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
    from ..git_manager import is_git_repo

    if not is_git_repo(repo):
        return "No git context available."
    parts: list[str] = []
    try:
        stat = subprocess.run(["git", "diff", "--stat"], cwd=str(repo), text=True, capture_output=True)
        if stat.stdout.strip():
            parts.append("Diff --stat:\n" + stat.stdout.strip())
    except subprocess.SubprocessError:
        pass
    except OSError:
        pass
    try:
        diff = subprocess.run(["git", "diff"], cwd=str(repo), text=True, capture_output=True)
        if diff.stdout.strip():
            parts.append("Diff:\n" + diff.stdout.strip())
    except subprocess.SubprocessError:
        pass
    except OSError:
        pass
    ctx = "\n\n".join(parts) if parts else "No diff available."
    return ctx[:max_chars]
