from __future__ import annotations

import json
import subprocess
from pathlib import Path
import typer
from rich import print

from .repo import ensure_repo
from .paths import Paths
from .settings import OpenRalphSettings, global_config_path, repo_config_path, STARTER_TOML
from .gitignore import GitignoreOptions, sync_gitignore, managed_block_is_current, render_managed_block
from .policies import ensure_policies
from .opencode_manager import ensure_opencode, install_opencode, find_opencode, opencode_version
from .opencode_config import write_opencode_json, OpenCodeConfigOptions
from .skills_generator import write_default_skills
from .tooling import ensure_tools, doctor_report
from .memory import init_db, index_repo, query_memory, vacuum_db
from .loop import run_loop

app = typer.Typer(help="OpenRalph: orchestrate OpenCode with skills, gates, git, and memory.")
config_app = typer.Typer(help="Manage openralph configuration.")
gitignore_app = typer.Typer(help="Manage repo .gitignore (openralph managed block).")
opencode_app = typer.Typer(help="Manage the bundled OpenCode binary.")
memory_app = typer.Typer(help="Memory index/query tools (SQLite + Ollama embeddings).")

app.add_typer(config_app, name="config")
app.add_typer(gitignore_app, name="gitignore")
app.add_typer(opencode_app, name="opencode")
app.add_typer(memory_app, name="memory")

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

@app.command()
def init(repo: str = typer.Argument(".", help="Repo path or git URL"),
         node_tooling: str | None = typer.Option(None, help="global|local"),
         create_venv: bool | None = typer.Option(None, help="Create .venv if missing")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    node_tooling = s.init_node_tooling if node_tooling is None else node_tooling
    create_venv = s.init_create_venv if create_venv is None else create_venv

    paths = Paths.for_repo(path)
    paths.ralph.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=True)
    ensure_policies(path)
    init_db(paths.memory_db)

    try:
        oc = ensure_opencode(path, auto_install=s.opencode_auto_install, version=s.opencode_version)
        print(f"[green]OpenCode[/green] {oc.path} ({oc.source})")
    except Exception as e:
        print(f"[red]OpenCode install failed[/red]: {e}")
        print("  [yellow]Hint:[/yellow] Run: openralph opencode install .")

    if s.init_with_opencode_json:
        ocfg = write_opencode_json(path, force=s.init_force_opencode_json, opts=OpenCodeConfigOptions(node_tooling=node_tooling))
        print(f"[green]Wrote[/green] {ocfg}")

    if s.init_write_skills:
        write_default_skills(path, force=s.init_force_skills)
        print("[green]Wrote[/green] .opencode/skills/*")

    opts = GitignoreOptions(ignore_reports=True, track_current_feature=True, node_tooling=node_tooling, playwright=s.init_playwright, ignore_venvs=True)
    sync_gitignore(path, opts)
    print("[green]Synced[/green] .gitignore (managed block)")

    if create_venv:
        venv_dir = path / ".venv"
        if not (venv_dir / "bin" / "python").exists() and not (path / "venv" / "bin" / "python").exists():
            subprocess.run(["python", "-m", "venv", str(venv_dir)], cwd=str(path), check=True)
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

    print(f"[green]Initialized[/green] {path}")

@app.command()
def doctor(repo: str = typer.Argument(".", help="Repo path")):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    all_ok = True

    oc = find_opencode(path)
    if oc:
        print(f"[green]OK[/green] opencode — {oc.source} ({opencode_version(oc.path)})")
    else:
        all_ok = False
        print("[red]FAIL[/red] opencode — not found")
        print("  [yellow]Hint:[/yellow] Run: openralph opencode install .")

    for r in doctor_report(repo=path, ollama_host=s.ollama_host, embed_model=s.embed_model, vacuum_warn_mb=s.memory_vacuum_warn_mb):
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
def run(repo: str = typer.Argument(".", help="Repo path"), prompt: str = typer.Argument(...), max_iters: int | None = typer.Option(None)):
    path = ensure_repo(repo)
    s = OpenRalphSettings.load(path)
    iters = s.loop_max_iters if max_iters is None else max_iters
    run_loop(path, prompt, max_iters=iters)
    print("[green]Done[/green]")
