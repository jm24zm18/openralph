from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import typer
from rich import print

from .repo import ensure_repo
from .paths import Paths
from .settings import OpenRalphSettings, global_config_path, repo_config_path, STARTER_TOML
from .logging import init_logging, LogConfig, get_logger, get_log_file
from .gitignore import GitignoreOptions, sync_gitignore, managed_block_is_current, render_managed_block
from .policies import ensure_policies
from .opencode_manager import ensure_opencode, install_opencode, find_opencode, opencode_version
from .opencode_config import write_opencode_json, OpenCodeConfigOptions, ProxyProviderOptions, AgentsOptions, AgentConfig
from .skills_generator import write_default_skills
from .tooling import ensure_tools, doctor_report, _find_system_python
from .memory import init_db, index_repo, query_memory, vacuum_db
from .loop import run_loop
from .proxy import ProxyConfig, start_proxy_background, stop_proxy, proxy_status, proxy_is_listening
from .prd import generate_prd, run_prd_qa, generate_prd_from_answers, save_prd_answers, load_prd_answers
from .features import create_feature, list_features, get_current_feature, set_current_feature, get_feature_context
from .agents import generate_agents_md, agents_md_exists

app = typer.Typer(help="OpenRalph: orchestrate OpenCode with skills, gates, git, and memory.")
config_app = typer.Typer(help="Manage openralph configuration.")
gitignore_app = typer.Typer(help="Manage repo .gitignore (openralph managed block).")
opencode_app = typer.Typer(help="Manage the bundled OpenCode binary.")
memory_app = typer.Typer(help="Memory index/query tools (SQLite + Ollama embeddings).")
proxy_app = typer.Typer(help="Manage the OpenCode API proxy server.")
prd_app = typer.Typer(help="Generate and manage Product Requirements Documents.")
feature_app = typer.Typer(help="Manage feature specification folders.")
agents_app = typer.Typer(help="Manage AGENTS.md and agent coordination.")

app.add_typer(config_app, name="config")
app.add_typer(gitignore_app, name="gitignore")
app.add_typer(opencode_app, name="opencode")
app.add_typer(memory_app, name="memory")
app.add_typer(proxy_app, name="proxy")
app.add_typer(prd_app, name="prd")
app.add_typer(feature_app, name="feature")
app.add_typer(agents_app, name="agents")


def _init_logging_for_repo(repo: Path, settings: OpenRalphSettings) -> None:
    paths = Paths.for_repo(repo)
    config = LogConfig(
        level=settings.log_level,
        console=settings.log_console,
        file=settings.log_file,
        file_path=None,
    )
    init_logging(config, log_dir=paths.logs)

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
        print(f"[yellow]Config already exists[/yellow] {target}")
        return
    target.write_text(STARTER_TOML, encoding="utf-8")
    print(f"[green]Wrote[/green] {target}")

@config_app.command("show")
def config_show(repo: str = typer.Option(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    print("[bold]Config paths[/bold]")
    print(f"  Global: {global_config_path()}")
    print(f"  Repo:   {repo_config_path(path)}")
    print("")
    print("[bold]Effective merged config[/bold]")
    print(json.dumps(s.as_dict(), indent=2))

@gitignore_app.command("show")
def gitignore_show(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=s.init_node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    print(render_managed_block(opts))

@gitignore_app.command("sync")
def gitignore_sync(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=s.init_node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    gi = sync_gitignore(path, opts)
    print(f"[green]Synced[/green] {gi}")

@opencode_app.command("install")
def opencode_install(repo: str = typer.Argument(".", help="Repo path"), version: str = typer.Option("", help="Version like 1.1.48 (empty = latest)")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    v = version or s.opencode_version
    p = install_opencode(path, version=v)
    print(f"[green]Installed[/green] {p}")
    print(f"[green]Version[/green] {opencode_version(p)}")

@opencode_app.command("where")
def opencode_where(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    found = find_opencode(path)
    if not found:
        print("[red]Not found[/red] (run: openralph opencode install)")
        raise typer.Exit(code=1)
    print(f"{found.path} ({found.source})")

@opencode_app.command("version")
def opencode_ver(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    found = find_opencode(path)
    if not found:
        print("[red]Not found[/red] (run: openralph opencode install)")
        raise typer.Exit(code=1)
    print(opencode_version(found.path))

@memory_app.command("index")
def memory_index_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    paths = Paths.for_repo(path)
    init_db(paths.memory_db)
    index_repo(path, paths.memory_db, s.ollama_host, s.embed_model,
              include_exts=set(s.memory_include_exts), exclude_dirs=set(s.memory_exclude_dirs),
              chunk_chars=s.memory_chunk_chars, chunk_overlap=s.memory_chunk_overlap)
    print(f"[green]Indexed[/green] {paths.memory_db}")

@memory_app.command("query")
def memory_query_cmd(repo: str = typer.Argument(".", help="Repo path"), q: str = typer.Argument(...), k: int | None = typer.Option(None)):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    paths = Paths.for_repo(path)
    kk = s.memory_k if k is None else k
    hits = query_memory(paths.memory_db, s.ollama_host, s.embed_model, q, k=kk)
    for h in hits:
        print(f"[bold]{h.path}#{h.chunk_index}[/bold] score={h.score:.3f}")
        print(h.content[:800])
        print("")

@memory_app.command("vacuum")
def memory_vacuum_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    paths = Paths.for_repo(path)
    vacuum_db(paths.memory_db)
    print(f"[green]Vacuumed[/green] {paths.memory_db}")

@proxy_app.command("start")
def proxy_start_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    paths = Paths.for_repo(path)

    if not s.proxy_enabled:
        print("[yellow]Proxy not enabled[/yellow] — set proxy.enabled = true in config")
        raise typer.Exit(code=1)

    running, existing_pid = proxy_status(paths.proxy_pid, s.proxy_listen_port)
    if running:
        print(f"[yellow]Proxy already running[/yellow] (PID {existing_pid}) on port {s.proxy_listen_port}")
        return

    if proxy_is_listening(s.proxy_listen_port):
        print(f"[red]Port {s.proxy_listen_port} already in use[/red]")
        raise typer.Exit(code=1)

    config = ProxyConfig(
        listen_port=s.proxy_listen_port,
        target_host=s.proxy_target_host,
        target_port=s.proxy_target_port,
        target_model=s.proxy_target_model,
    )
    pid = start_proxy_background(config, paths.proxy_pid, paths.proxy_log)
    print(f"[green]Started[/green] proxy (PID {pid}) on port {s.proxy_listen_port}")
    print(f"  Target: {s.proxy_target_host}:{s.proxy_target_port}")
    print(f"  Model:  {s.proxy_target_model}")
    print(f"  Log:    {paths.proxy_log}")

@proxy_app.command("stop")
def proxy_stop_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    paths = Paths.for_repo(path)

    if stop_proxy(paths.proxy_pid):
        print("[green]Stopped[/green] proxy")
    else:
        print("[yellow]Proxy not running[/yellow]")

@proxy_app.command("status")
def proxy_status_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    paths = Paths.for_repo(path)

    if not s.proxy_enabled:
        print("[yellow]Proxy not enabled[/yellow] — set proxy.enabled = true in config")
        return

    running, pid = proxy_status(paths.proxy_pid, s.proxy_listen_port)
    if running:
        print(f"[green]Running[/green] (PID {pid}) on port {s.proxy_listen_port}")
        print(f"  Target: {s.proxy_target_host}:{s.proxy_target_port}")
        print(f"  Model:  {s.proxy_target_model}")
    else:
        print("[yellow]Not running[/yellow]")

@proxy_app.command("config")
def proxy_config_cmd(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    print("[bold]Proxy configuration[/bold]")
    print(f"  enabled:          {s.proxy_enabled}")
    print(f"  listen_port:      {s.proxy_listen_port}")
    print(f"  target_host:      {s.proxy_target_host}")
    print(f"  target_port:      {s.proxy_target_port}")
    print(f"  target_model:     {s.proxy_target_model}")
    print(f"  provider_name:    {s.proxy_provider_name}")
    print(f"  provider_display: {s.proxy_provider_display}")
    print(f"  model_id:         {s.proxy_model_id}")
    print(f"  model_display:    {s.proxy_model_display}")
    print(f"  api_key:          {s.proxy_api_key}")
    print(f"  auto_start:       {s.proxy_auto_start}")

@app.command()
def init(repo: str = typer.Argument(".", help="Repo path or git URL"),
         node_tooling: str | None = typer.Option(None, help="global|local"),
         create_venv: bool | None = typer.Option(None, help="Create .venv if missing"),
         log_level: str | None = typer.Option(None, help="Log level: DEBUG, INFO, WARNING, ERROR")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
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
    ensure_policies(path)
    init_db(paths.memory_db)

    try:
        oc = ensure_opencode(path, auto_install=s.opencode_auto_install, version=s.opencode_version)
        log.info("OpenCode found: %s (%s)", oc.path, oc.source)
        print(f"[green]OpenCode[/green] {oc.path} ({oc.source})")
    except Exception as e:
        log.error("OpenCode install failed: %s", e, exc_info=True)
        print(f"[red]OpenCode install failed[/red]: {e}")
        print("  [yellow]Hint:[/yellow] Run: openralph opencode install .")

    if s.init_with_opencode_json:
        proxy_opts = ProxyProviderOptions(
            enabled=s.proxy_enabled,
            listen_port=s.proxy_listen_port,
            provider_name=s.proxy_provider_name,
            provider_display=s.proxy_provider_display,
            model_id=s.proxy_model_id,
            model_display=s.proxy_model_display,
            api_key=s.proxy_api_key,
        )
        agents_opts = AgentsOptions(
            enabled=s.agents_enabled,
            default_provider=s.agents_default_provider,
            default_model=s.agents_default_model,
            code=AgentConfig(name="code", model=s.agent_code_model, permissions=tuple(s.agent_code_permissions)),
            plan=AgentConfig(name="plan", model=s.agent_plan_model, permissions=tuple(s.agent_plan_permissions)),
            test=AgentConfig(name="test", model=s.agent_test_model, permissions=tuple(s.agent_test_permissions)),
            review=AgentConfig(name="review", model=s.agent_review_model, permissions=tuple(s.agent_review_permissions)),
        )
        ocfg = write_opencode_json(path, force=s.init_force_opencode_json, opts=OpenCodeConfigOptions(node_tooling=node_tooling, proxy=proxy_opts, agents=agents_opts))
        print(f"[green]Wrote[/green] {ocfg}")

    if s.init_write_skills:
        write_default_skills(path, force=s.init_force_skills)
        print("[green]Wrote[/green] .opencode/skills/*")

    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    sync_gitignore(path, opts)
    print("[green]Synced[/green] .gitignore (managed block)")

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
            print("[green]Created[/green] .venv")

    if s.init_install_tools:
        results = ensure_tools(repo=path, install=True, node_tooling=node_tooling,
                              install_playwright=s.init_playwright, install_playwright_browsers=s.init_playwright_browsers,
                              ollama_host=s.ollama_host, embed_model=s.embed_model)
        for r in results:
            if r.ok:
                print(f"[green]OK[/green] {r.name} — {r.detail}")
            else:
                print(f"[red]FAIL[/red] {r.name} — {r.detail}")
                if r.hint:
                    print(f"  [yellow]Hint:[/yellow] {r.hint}")

    if s.proxy_enabled and s.proxy_auto_start:
        running, existing_pid = proxy_status(paths.proxy_pid, s.proxy_listen_port)
        if running:
            print(f"[green]OK[/green] proxy — already running (PID {existing_pid})")
        elif proxy_is_listening(s.proxy_listen_port):
            print(f"[yellow]WARN[/yellow] proxy — port {s.proxy_listen_port} in use by another process")
        else:
            config = ProxyConfig(
                listen_port=s.proxy_listen_port,
                target_host=s.proxy_target_host,
                target_port=s.proxy_target_port,
                target_model=s.proxy_target_model,
            )
            pid = start_proxy_background(config, paths.proxy_pid, paths.proxy_log)
            print(f"[green]Started[/green] proxy (PID {pid}) on port {s.proxy_listen_port}")

    log.info("Repository initialized successfully: %s", path)
    log_file = get_log_file()
    if log_file:
        print(f"[green]Log file[/green] {log_file}")
    print(f"[green]Initialized[/green] {path}")

@app.command()
def doctor(repo: str = typer.Argument(".", help="Repo path"),
           log_level: str | None = typer.Option(None, help="Log level: DEBUG, INFO, WARNING, ERROR")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    if log_level:
        s.log_level = log_level
    _init_logging_for_repo(path, s)
    log = get_logger("cli")
    log.info("Running doctor check on: %s", path)
    all_ok = True

    oc = find_opencode(path)
    if oc:
        print(f"[green]OK[/green] opencode — {oc.source} ({opencode_version(oc.path)})")
    else:
        all_ok = False
        print("[red]FAIL[/red] opencode — not found")
        print("  [yellow]Hint:[/yellow] Run: openralph opencode install .")

    for r in doctor_report(repo=path, ollama_host=s.ollama_host, embed_model=s.embed_model, vacuum_warn_mb=s.memory_vacuum_warn_mb,
                           proxy_enabled=s.proxy_enabled, proxy_listen_port=s.proxy_listen_port):
        if r.ok:
            print(f"[green]OK[/green] {r.name} — {r.detail}")
        else:
            all_ok = False
            print(f"[red]FAIL[/red] {r.name} — {r.detail}")
            if r.hint:
                print(f"  [yellow]Hint:[/yellow] {r.hint}")

    gi_opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=s.init_node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    if not managed_block_is_current(path, gi_opts):
        all_ok = False
        print("[red]FAIL[/red] gitignore — managed block missing or out of date")
        print("  [yellow]Hint:[/yellow] Run: openralph gitignore sync .")

    if all_ok:
        print("[green]All checks passed.[/green]")
    else:
        raise typer.Exit(code=1)

@app.command()
def run(repo: str = typer.Argument(".", help="Repo path"), prompt: str = typer.Argument(...),
        max_iters: int | None = typer.Option(None),
        log_level: str | None = typer.Option(None, help="Log level: DEBUG, INFO, WARNING, ERROR")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    if log_level:
        s.log_level = log_level
    _init_logging_for_repo(path, s)
    log = get_logger("cli")
    iters = s.loop_max_iters if max_iters is None else max_iters
    log.info("Starting run loop with prompt: %s (max_iters=%d)", prompt[:100], iters)
    run_loop(path, prompt, max_iters=iters)
    log.info("Run loop completed")
    log_file = get_log_file()
    if log_file:
        print(f"[green]Log file[/green] {log_file}")
    print("[green]Done[/green]")


# ========== PRD Commands ==========

@prd_app.command("generate")
def prd_generate_cmd(
    repo: str = typer.Argument(".", help="Repo path"),
    output: str | None = typer.Option(None, help="Output path (default: docs/PRD.md)"),
    force: bool = typer.Option(False, help="Overwrite existing PRD"),
):
    """Generate a PRD from repository context using OpenCode."""
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    _init_logging_for_repo(path, s)

    output_path = Path(output) if output else path / "docs" / "PRD.md"
    if output_path.exists() and not force:
        print(f"[yellow]PRD already exists[/yellow] {output_path}")
        print("  Use --force to overwrite")
        raise typer.Exit(code=1)

    print("[cyan]Generating PRD...[/cyan] (this may take a moment)")
    try:
        result = generate_prd(path, output_path)
        print(f"[green]Wrote[/green] {result}")
    except Exception as e:
        print(f"[red]Failed[/red]: {e}")
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
        print("[cyan]Found existing PRD answers.[/cyan]")
        use_existing = input("Use existing answers? (y/n) > ").strip().lower()
        if use_existing == "y":
            result = generate_prd_from_answers(path, existing, output_path)
            print(f"[green]Wrote[/green] {result}")
            return

    answers = run_prd_qa(path)
    save_prd_answers(path, answers)
    print(f"[green]Saved answers[/green] .ralph/prd-answers.json")

    result = generate_prd_from_answers(path, answers, output_path)
    print(f"[green]Wrote[/green] {result}")


@prd_app.command("show")
def prd_show_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """Show the current PRD."""
    path = ensure_repo(repo)
    prd_path = path / "docs" / "PRD.md"
    if not prd_path.exists():
        print("[yellow]No PRD found[/yellow]")
        print("  Run: openralph prd generate .")
        raise typer.Exit(code=1)
    print(prd_path.read_text(encoding="utf-8"))


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
    print(f"[green]Created[/green] {feature.path}")
    print(f"  00-brief.md")
    print(f"  01-requirements.md")
    print(f"  03-test-plan.md")
    print(f"[green]Set current feature[/green] .ralph/CURRENT_FEATURE")


@feature_app.command("list")
def feature_list_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """List all feature folders."""
    path = ensure_repo(repo)
    features = list_features(path)
    if not features:
        print("[yellow]No features found[/yellow]")
        print("  Run: openralph feature new . \"Feature title\"")
        return

    for f in features:
        marker = "[cyan]*[/cyan] " if f.is_current else "  "
        print(f"{marker}{f.date_str} {f.title}")
        print(f"    {f.path}")


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
            print(f"[red]Feature not found[/red]: {feature_path}")
            raise typer.Exit(code=1)
        set_current_feature(path, feature_path)
        print(f"[green]Set current feature[/green] {set_path}")
        return

    current = get_current_feature(path)
    if current:
        print(f"[bold]Current feature:[/bold] {current.relative_to(path)}")
        # Show brief if exists
        brief = current / "00-brief.md"
        if brief.exists():
            print("")
            print(brief.read_text(encoding="utf-8")[:500])
    else:
        print("[yellow]No current feature set[/yellow]")
        print("  Run: openralph feature new . \"Feature title\"")


@feature_app.command("context")
def feature_context_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """Show the current feature context (for prompts)."""
    path = ensure_repo(repo)
    context = get_feature_context(path)
    if context:
        print(context)
    else:
        print("[yellow]No current feature set[/yellow]")


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
        print(f"[green]Wrote[/green] {result}")
    except FileExistsError as e:
        print(f"[yellow]AGENTS.md already exists[/yellow]")
        print("  Use --force to overwrite")
        raise typer.Exit(code=1)


@agents_app.command("show")
def agents_show_cmd(repo: str = typer.Argument(".", help="Repo path")):
    """Show the current AGENTS.md."""
    path = ensure_repo(repo)
    agents_path = path / "AGENTS.md"
    if not agents_path.exists():
        print("[yellow]No AGENTS.md found[/yellow]")
        print("  Run: openralph agents init .")
        raise typer.Exit(code=1)
    print(agents_path.read_text(encoding="utf-8"))
