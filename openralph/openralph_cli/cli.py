from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path
import typer
from .ui import (
    console,
    doctor_table,
    config_table,
    feature_table,
    proxy_panel,
    memory_results,
    init_results_panel,
    notice,
    scaffold_created,
    set_cli_ui_overrides,
)

from .repo import ensure_repo
from .paths import Paths
from .settings import ConfigLoadError, OpenRalphSettings, global_config_path, repo_config_path, STARTER_TOML
from .git_manager import is_git_repo
from .logging import init_logging, LogConfig, get_logger, get_log_file
from .gitignore import GitignoreOptions, sync_gitignore, managed_block_is_current, render_managed_block
from .policies import ensure_policies
from .tooling import ensure_tools, doctor_report, _find_system_python
from .memory import init_db, index_repo, query_memory, vacuum_db
from .loop import run_loop
from .loop.status import RunOutcome, write_run_artifacts
from .proxy import ProxyConfig, start_proxy_background, stop_proxy, proxy_status, proxy_is_listening
from .prd import (
    PRDEmptyOutputError,
    PRDGenerationError,
    PRDProviderConnectionError,
    PRDProviderRequestError,
    generate_prd,
    run_prd_qa,
    generate_prd_from_answers,
    save_prd_answers,
    load_prd_answers,
)
from .features import create_feature, create_bug, list_features, get_current_feature, set_current_feature, get_feature_context
from .agents import generate_agents_md, agents_md_exists

app = typer.Typer(help="OpenRalph: orchestrate native agents with skills, gates, git, and memory.")
config_app = typer.Typer(help="Manage openralph configuration.")
gitignore_app = typer.Typer(help="Manage repo .gitignore (openralph managed block).")
memory_app = typer.Typer(help="Memory index/query tools (SQLite + Ollama embeddings).")
proxy_app = typer.Typer(help="Manage the LLM proxy server.")
prd_app = typer.Typer(help="Generate and manage Product Requirements Documents.")
feature_app = typer.Typer(help="Manage feature specification folders.")
bug_app = typer.Typer(help="Manage bug specification folders.")
agents_app = typer.Typer(help="Manage AGENTS.md and agent coordination.")

app.add_typer(config_app, name="config")
app.add_typer(gitignore_app, name="gitignore")
app.add_typer(memory_app, name="memory")
app.add_typer(proxy_app, name="proxy")
app.add_typer(prd_app, name="prd")
app.add_typer(feature_app, name="feature")
app.add_typer(bug_app, name="bug")
app.add_typer(agents_app, name="agents")


@app.callback(invoke_without_command=True)
def main(
    plain: bool = typer.Option(False, "--plain", help="Force plain output (no Rich panels/live UI)."),
    ui_style: str = typer.Option("signature", "--ui-style", help="UI style: signature|minimal"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=lambda v: _version_callback(v),
        is_eager=True,
        help="Show OpenRalph version and exit.",
    ),
):
    _ = version
    if ui_style not in ("signature", "minimal"):
        raise typer.BadParameter("ui-style must be one of: signature, minimal")
    set_cli_ui_overrides(True if plain else None, ui_style)


def _version_callback(value: bool) -> bool:
    if not value:
        return value
    try:
        v = importlib.metadata.version("openralph")
    except importlib.metadata.PackageNotFoundError:
        v = "0.0.0+local"
    typer.echo(f"openralph {v}")
    raise typer.Exit()


def _init_logging_for_repo(repo: Path, settings: OpenRalphSettings) -> None:
    paths = Paths.for_repo(repo)
    config = LogConfig(
        level=settings.log_level,
        console=settings.log_console,
        file=settings.log_file,
        raw_debug=settings.log_raw_debug,
        file_path=None,
    )
    init_logging(config, log_dir=paths.logs)


def _load_settings_or_exit(path: Path) -> OpenRalphSettings:
    try:
        return OpenRalphSettings.load(path)
    except ConfigLoadError as e:
        where = f" in {e.path}" if e.path else ""
        key = f" ({e.key_path})" if e.key_path else ""
        notice(
            f"Invalid config{where}{key}: {e}",
            level="error",
            hint="Fix .openralph.toml (or global config) and retry.",
        )
        raise typer.Exit(code=2)

@config_app.command("init")
def config_init(
    repo: str = typer.Option(".", help="Repo path (for repo config)"),
    scope: str = typer.Option("repo", help="repo|global"),
    force: bool = typer.Option(False, help="Overwrite existing config"),
):
    path = ensure_repo(repo)
    if scope not in ("repo", "global"):
        raise typer.BadParameter("scope must be repo or global")
    target = repo_config_path(path) if scope == "repo" else global_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        notice(f"Config already exists: {target}", level="warn")
        return
    target.write_text(STARTER_TOML, encoding="utf-8")
    notice(f"Wrote config: {target}", level="success")

@config_app.command("show")
def config_show(
    repo: str = typer.Argument(".", metavar="[REPO]", help="Repo path"),
    repo_flag: str | None = typer.Option(None, "--repo", help="Repo path (alternative flag form)"),
):
    path = ensure_repo(repo_flag or repo)
    s = _load_settings_or_exit(path)
    config_table(s.as_dict(), global_config_path(), repo_config_path(path))

@gitignore_app.command("show")
def gitignore_show(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=s.init_node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    console.print(render_managed_block(opts))

@gitignore_app.command("sync")
def gitignore_sync(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=s.init_node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    gi = sync_gitignore(path, opts)
    notice(f"Synced gitignore: {gi}", level="success")

@memory_app.command("index")
def memory_index_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    paths = Paths.for_repo(path)
    init_db(paths.memory_db)
    index_repo(path, paths.memory_db, s.ollama_host, s.embed_model,
              include_exts=set(s.memory_include_exts), exclude_dirs=set(s.memory_exclude_dirs),
              chunk_chars=s.memory_chunk_chars, chunk_overlap=s.memory_chunk_overlap)
    notice(f"Indexed memory DB: {paths.memory_db}", level="success")

@memory_app.command("query")
def memory_query_cmd(repo: str = typer.Argument(".", help="Repo path"), q: str = typer.Argument(...), k: int | None = typer.Option(None)):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    paths = Paths.for_repo(path)
    kk = s.memory_k if k is None else k
    hits = query_memory(paths.memory_db, s.ollama_host, s.embed_model, q, k=kk)
    memory_results(hits)

@memory_app.command("vacuum")
def memory_vacuum_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    paths = Paths.for_repo(path)
    vacuum_db(paths.memory_db)
    notice(f"Vacuumed memory DB: {paths.memory_db}", level="success")

@proxy_app.command("start")
def proxy_start_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    paths = Paths.for_repo(path)

    if not s.proxy_enabled:
        notice("Proxy not enabled", level="warn", hint="Set proxy.enabled = true in config")
        raise typer.Exit(code=1)

    running, existing_pid = proxy_status(paths.proxy_pid, s.proxy_listen_port)
    if running:
        notice(f"Proxy already running (PID {existing_pid}) on port {s.proxy_listen_port}", level="warn")
        return

    if proxy_is_listening(s.proxy_listen_port):
        notice(f"Port {s.proxy_listen_port} already in use", level="error")
        raise typer.Exit(code=1)

    config = ProxyConfig(
        listen_port=s.proxy_listen_port,
        target_host=s.proxy_target_host,
        target_port=s.proxy_target_port,
        target_model=s.proxy_target_model,
        log_requests=s.proxy_log_requests,
        cors_enabled=s.proxy_cors_enabled,
        cors_allow_origin=s.proxy_cors_allow_origin,
    )
    pid = start_proxy_background(config, paths.proxy_pid, paths.proxy_log)
    proxy_panel(
        "Proxy Started",
        status=f"[green]Running[/green] (PID {pid})",
        port=str(s.proxy_listen_port),
        target=f"{s.proxy_target_host}:{s.proxy_target_port}",
        model=s.proxy_target_model,
        log=str(paths.proxy_log),
    )

@proxy_app.command("stop")
def proxy_stop_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    paths = Paths.for_repo(path)

    if stop_proxy(paths.proxy_pid):
        notice("Stopped proxy", level="success")
    else:
        notice("Proxy not running", level="warn")

@proxy_app.command("status")
def proxy_status_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    paths = Paths.for_repo(path)

    if not s.proxy_enabled:
        notice("Proxy not enabled", level="warn", hint="Set proxy.enabled = true in config")
        return

    running, pid = proxy_status(paths.proxy_pid, s.proxy_listen_port)
    if running:
        proxy_panel(
            "Proxy Status",
            status=f"[green]Running[/green] (PID {pid})",
            port=str(s.proxy_listen_port),
            target=f"{s.proxy_target_host}:{s.proxy_target_port}",
            model=s.proxy_target_model,
        )
    else:
        notice("Proxy not running", level="warn")

@proxy_app.command("config")
def proxy_config_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    proxy_panel(
        "Proxy Configuration",
        enabled=str(s.proxy_enabled),
        listen_port=str(s.proxy_listen_port),
        target_host=s.proxy_target_host,
        target_port=str(s.proxy_target_port),
        target_model=s.proxy_target_model,
        provider_name=s.proxy_provider_name,
        provider_display=s.proxy_provider_display,
        model_id=s.proxy_model_id,
        model_display=s.proxy_model_display,
        api_key=s.proxy_api_key,
        auto_start=str(s.proxy_auto_start),
        cors_enabled=str(s.proxy_cors_enabled),
        cors_allow_origin=s.proxy_cors_allow_origin,
    )

@app.command()
def init(repo: str = typer.Argument(".", help="Repo path or git URL"),
         node_tooling: str | None = typer.Option(None, help="global|local"),
         create_venv: bool | None = typer.Option(None, help="Create .venv if missing"),
         log_level: str | None = typer.Option(None, help="Log level: DEBUG, INFO, WARNING, ERROR")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    if log_level:
        s.log_level = log_level
    node_tooling = s.init_node_tooling if node_tooling is None else node_tooling
    create_venv = s.init_create_venv if create_venv is None else create_venv

    paths = Paths.for_repo(path)
    paths.ralph.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=True)
    _init_logging_for_repo(path, s)
    log = get_logger("cli")
    log.info("Initializing repository: %s", path)

    init_items: list[tuple[str, str, str]] = []

    # Auto-init git if not already a git repo
    if not is_git_repo(path):
        log.info("Initializing git repository")
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, text=True, check=True)
        subprocess.run(["git", "add", "-A"], cwd=str(path), capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit (openralph init)", "--allow-empty"],
            cwd=str(path), capture_output=True, text=True,
        )
        init_items.append(("ok", "git", "initialized repository"))

    ensure_policies(path)
    init_db(paths.memory_db)

    if s.agent_native:
        log.info("Native agent enabled")
        init_items.append(("ok", "agent", f"native mode (proxy port {s.proxy_listen_port})"))
    else:
        log.error("agent.native is false, but OpenCode support has been removed.")
        notice("Config error: agent.native is false, but OpenCode support has been removed.", level="error")
        raise typer.Exit(code=1)

    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    sync_gitignore(path, opts)
    gi_ok = managed_block_is_current(path, opts)
    if gi_ok:
        init_items.append(("ok", "gitignore", "synced managed block"))
    else:
        init_items.append(("fail", "gitignore", "managed block missing/out of date"))

    if create_venv:
        import os
        venv_dir = path / ".venv"
        if os.name == "nt":
            venv_exists = (venv_dir / "Scripts" / "python.exe").exists() or (path / "venv" / "Scripts" / "python.exe").exists()
        else:
            venv_exists = (venv_dir / "bin" / "python").exists() or (path / "venv" / "bin" / "python").exists()
        if not venv_exists:
            system_py = _find_system_python()
            subprocess.run([system_py, "-m", "venv", str(venv_dir)], cwd=str(path), check=True)
            init_items.append(("ok", "venv", "created .venv"))

    if s.init_install_tools:
        results = ensure_tools(repo=path, install=True, node_tooling=node_tooling,
                              install_playwright=s.init_playwright, install_playwright_browsers=s.init_playwright_browsers,
                              install_playwright_cli=s.init_playwright_cli,
                              ollama_host=s.ollama_host, embed_model=s.embed_model)
        for r in results:
            status = "ok" if r.ok else "fail"
            detail = r.detail
            if r.hint and not r.ok:
                detail += f" (hint: {r.hint})"
            init_items.append((status, r.name, detail))

    if s.proxy_enabled and s.proxy_auto_start:
        running, existing_pid = proxy_status(paths.proxy_pid, s.proxy_listen_port)
        if running:
            init_items.append(("ok", "proxy", f"already running (PID {existing_pid})"))
        elif proxy_is_listening(s.proxy_listen_port):
            init_items.append(("warn", "proxy", f"port {s.proxy_listen_port} in use by another process"))
        else:
            config = ProxyConfig(
                listen_port=s.proxy_listen_port,
                target_host=s.proxy_target_host,
                target_port=s.proxy_target_port,
                target_model=s.proxy_target_model,
                log_requests=s.proxy_log_requests,
                cors_enabled=s.proxy_cors_enabled,
                cors_allow_origin=s.proxy_cors_allow_origin,
            )
            pid = start_proxy_background(config, paths.proxy_pid, paths.proxy_log)
            init_items.append(("ok", "proxy", f"started (PID {pid}) on port {s.proxy_listen_port}"))

    log.info("Repository initialized successfully: %s", path)
    log_file = get_log_file()
    if log_file:
        init_items.append(("ok", "log", str(log_file)))

    init_results_panel(init_items)
    failed = any(state == "fail" for state, _name, _detail in init_items)
    if failed:
        notice("Initialization completed with failures. Run `openralph doctor .` for details.", level="error")
        raise typer.Exit(code=1)
    notice(f"Initialized repository: {path}", level="success")

@app.command()
def doctor(repo: str = typer.Argument(".", help="Repo path"),
           log_level: str | None = typer.Option(None, help="Log level: DEBUG, INFO, WARNING, ERROR")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    if log_level:
        s.log_level = log_level
    _init_logging_for_repo(path, s)
    log = get_logger("cli")
    log.info("Running doctor check on: %s", path)

    agent_ok = s.agent_native
    agent_detail = f"native mode (proxy port {s.proxy_listen_port})" if agent_ok else "native mode disabled"

    results = doctor_report(repo=path, ollama_host=s.ollama_host, embed_model=s.embed_model, vacuum_warn_mb=s.memory_vacuum_warn_mb,
                            proxy_enabled=s.proxy_enabled, proxy_listen_port=s.proxy_listen_port,
                            sandbox_mode=s.sandbox_mode)

    gi_opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=s.init_node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    gi_ok = managed_block_is_current(path, gi_opts)
    if not gi_ok:
        alt_node_tooling = "local" if s.init_node_tooling == "global" else "global"
        alt_opts = GitignoreOptions(
            ignore_reports=True,
            track_current_feature=True,
            node_tooling=alt_node_tooling,
            playwright=s.init_playwright,
            ignore_venvs=True,
        )
        gi_ok = managed_block_is_current(path, alt_opts)

    doctor_table(results, agent_ok, agent_detail, gi_ok)

    all_ok = agent_ok and gi_ok and all(r.ok for r in results)
    if not all_ok:
        raise typer.Exit(code=1)

@app.command()
def run(repo: str = typer.Argument(".", help="Repo path"), prompt: str = typer.Argument(...),
        max_iters: int | None = typer.Option(None),
        mode: str = typer.Option("standard", "--mode", help="Execution mode: standard|fast"),
        prd_refresh_every: int | None = typer.Option(None, help="Regenerate PRD every N iterations (0 disables)"),
        prd_refresh_mode: str | None = typer.Option(None, help="PRD refresh mode: '' or 'ask'"),
        prd_qa_mode: str | None = typer.Option(None, help="PRD Q&A mode: interactive|handoff|auto|auto-then-handoff"),
        auto: str | None = typer.Option(None, "--auto", help="Automation mode: 'full' = PRD + plan + build all features"),
        log_level: str | None = typer.Option(None, help="Log level: DEBUG, INFO, WARNING, ERROR")):
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    if log_level:
        s.log_level = log_level
    if prd_refresh_every is not None:
        s.loop_prd_refresh_every = prd_refresh_every
    if prd_refresh_mode is not None:
        s.loop_prd_refresh_mode = prd_refresh_mode
    if prd_qa_mode is not None:
        s.loop_prd_qa_mode = prd_qa_mode
    if auto is not None:
        s.loop_auto_mode = auto
        # In full auto mode, force PRD auto-generation if no explicit prd_qa_mode given
        if auto == "full" and prd_qa_mode is None:
            s.loop_prd_qa_mode = "auto"
    if mode not in {"standard", "fast"}:
        notice(f"Invalid mode: {mode}", level="error", hint="Use --mode standard or --mode fast")
        raise typer.Exit(code=2)
    _init_logging_for_repo(path, s)
    log = get_logger("cli")
    iters = s.loop_max_iters if max_iters is None else max_iters
    log.info("Starting run loop with prompt: %s (max_iters=%d, auto=%s)", prompt[:100], iters, s.loop_auto_mode or "off")
    try:
        outcome = run_loop(path, prompt, max_iters=iters, settings=s, mode=mode)
    except Exception as e:
        log.error("Run loop raised unexpectedly: %s", e, exc_info=True)
        outcome = RunOutcome(
            status="failed",
            reason=f"run_loop_crashed: {e}",
            stage="run",
        )
    run_status = Paths.for_repo(path).run_status
    run_summary = Paths.for_repo(path).run_summary
    if (not run_status.exists()) or (not run_summary.exists()):
        write_run_artifacts(
            run_status,
            run_summary,
            outcome=outcome,
            prompt=prompt,
            auto_mode=s.loop_auto_mode,
        )
    log.info("Run loop completed: status=%s reason=%s", outcome.status, outcome.reason)
    log_file = get_log_file()
    if log_file:
        notice(f"Log file: {log_file}", level="info")
    if outcome.status == "success":
        notice("Run complete", level="success")
    elif outcome.status == "success_with_warnings":
        notice(
            "Run complete with warnings",
            level="warn",
            hint=(
                f"tool_errors={outcome.tool_errors}, "
                f"max_tool_errors={outcome.max_tool_errors}"
            ),
        )
    elif outcome.ok:
        notice("Run complete", level="success")
    else:
        detail = f"Run ended with status '{outcome.status}'"
        if outcome.reason:
            detail += f": {outcome.reason}"
        notice(detail, level="error", hint="See .ralph/RUN_SUMMARY.md and .ralph/RUN_STATUS.json")
        raise typer.Exit(code=1)


# ========== PRD Commands ==========

@prd_app.command("generate")
def prd_generate_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    output: str | None = typer.Option(None, help="Output path (default: docs/PRD.md)"),
    force: bool = typer.Option(False, help="Overwrite existing PRD"),
):
    """Generate a PRD from repository context using the native agent."""
    path = ensure_repo(repo)
    s = _load_settings_or_exit(path)
    _init_logging_for_repo(path, s)

    output_path = Path(output) if output else path / "docs" / "PRD.md"
    if output_path.exists() and not force:
        notice(f"PRD already exists: {output_path}", level="warn", hint="Use --force to overwrite")
        raise typer.Exit(code=1)

    notice("Generating PRD (this may take a moment)", level="info")
    try:
        result = generate_prd(path, output_path)
        notice(f"Wrote PRD: {result}", level="success")
    except PRDProviderConnectionError as e:
        notice(
            f"Failed to generate PRD: {e}",
            level="error",
            hint="Verify provider/proxy connectivity and run: openralph doctor .",
        )
        raise typer.Exit(code=1)
    except PRDProviderRequestError as e:
        notice(
            f"Failed to generate PRD: {e}",
            level="error",
            hint="Check provider model/config and inspect latest .ralph/logs/openralph_*.log",
        )
        raise typer.Exit(code=1)
    except PRDEmptyOutputError as e:
        notice(
            f"Failed to generate PRD: {e}",
            level="error",
            hint="Provider returned no text; inspect logs and retry after provider health check.",
        )
        raise typer.Exit(code=1)
    except PRDGenerationError as e:
        notice(f"Failed to generate PRD: {e}", level="error", hint="Check .ralph/logs for details.")
        raise typer.Exit(code=1)


@prd_app.command("qa")
def prd_qa_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    output: str | None = typer.Option(None, help="Output path (default: docs/PRD.md)"),
):
    """Run interactive Q&A to generate a PRD."""
    path = ensure_repo(repo)
    output_path = Path(output) if output else path / "docs" / "PRD.md"

    # Check for existing answers
    existing = load_prd_answers(path)
    if existing:
        notice("Found existing PRD answers.", level="info")
        use_existing = input("Use existing answers? (y/n) > ").strip().lower()
        if use_existing == "y":
            result = generate_prd_from_answers(path, existing, output_path)
            notice(f"Wrote PRD: {result}", level="success")
            return

    answers = run_prd_qa(path)
    save_prd_answers(path, answers)
    notice("Saved answers: .ralph/prd-answers.json", level="success")

    result = generate_prd_from_answers(path, answers, output_path)
    notice(f"Wrote PRD: {result}", level="success")


@prd_app.command("show")
def prd_show_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """Show the current PRD."""
    path = ensure_repo(repo)
    prd_path = path / "docs" / "PRD.md"
    if not prd_path.exists():
        notice("No PRD found.", level="warn", hint="Run: openralph prd generate .")
        raise typer.Exit(code=1)
    console.print(prd_path.read_text(encoding="utf-8"))


# ========== Feature Commands ==========

@feature_app.command("new")
def feature_new_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    title: str = typer.Argument(..., help="Feature title"),
    description: str = typer.Option("", help="Short description"),
):
    """Create a new feature folder with required files."""
    path = ensure_repo(repo)
    feature = create_feature(path, title, description)
    scaffold_created(
        title="Feature Created",
        path=str(feature.path),
        files=["00-brief.md", "01-requirements.md", "03-test-plan.md"],
        footer="Current feature set in .ralph/CURRENT_FEATURE",
    )


# ========== Bug Commands ==========

@bug_app.command("new")
def bug_new_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    title: str = typer.Argument(..., help="Bug title"),
    description: str = typer.Option("", help="Short description"),
):
    """Create a new bug folder with required files."""
    path = ensure_repo(repo)
    bug = create_bug(path, title, description)
    scaffold_created(
        title="Bug Spec Created",
        path=str(bug.path),
        files=["00-brief.md", "01-requirements.md", "03-test-plan.md"],
        footer="Current feature set in .ralph/CURRENT_FEATURE",
    )


@feature_app.command("list")
def feature_list_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """List all feature folders."""
    path = ensure_repo(repo)
    features = list_features(path)
    if not features:
        notice("No features found.", level="warn", hint='Run: openralph feature new . "Feature title"')
        return

    feature_table(features)


@feature_app.command("current")
def feature_current_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    set_path: str | None = typer.Option(None, "--set", help="Set current feature by path"),
):
    """Show or set the current feature."""
    path = ensure_repo(repo)

    if set_path:
        feature_path = path / set_path
        if not feature_path.exists():
            notice(f"Feature not found: {feature_path}", level="error")
            raise typer.Exit(code=1)
        set_current_feature(path, feature_path)
        notice(f"Set current feature: {set_path}", level="success")
        return

    current = get_current_feature(path)
    if current:
        notice(f"Current feature: {current.relative_to(path)}", level="info")
        # Show brief if exists
        brief = current / "00-brief.md"
        if brief.exists():
            console.print(brief.read_text(encoding="utf-8")[:500])
    else:
        notice("No current feature set.", level="warn", hint='Run: openralph feature new . "Feature title"')


@feature_app.command("context")
def feature_context_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """Show the current feature context (for prompts)."""
    path = ensure_repo(repo)
    context = get_feature_context(path)
    if context:
        console.print(context)
    else:
        notice("No current feature set.", level="warn")


# ========== Agents Commands ==========

@agents_app.command("init")
def agents_init_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    force: bool = typer.Option(False, help="Overwrite existing AGENTS.md"),
):
    """Generate AGENTS.md in the repository root."""
    path = ensure_repo(repo)
    try:
        result = generate_agents_md(path, force=force)
        notice(f"Wrote AGENTS.md: {result}", level="success")
    except FileExistsError as e:
        notice("AGENTS.md already exists.", level="warn", hint="Use --force to overwrite")
        raise typer.Exit(code=1)


@agents_app.command("show")
def agents_show_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """Show the current AGENTS.md."""
    path = ensure_repo(repo)
    agents_path = path / "AGENTS.md"
    if not agents_path.exists():
        notice("No AGENTS.md found.", level="warn", hint="Run: openralph agents init .")
        raise typer.Exit(code=1)
    console.print(agents_path.read_text(encoding="utf-8"))
