from __future__ import annotations

import json

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .components import kv_panel, metric_table, status_badge
from .context import console, ui_context


def notice(message: str, level: str = "info", hint: str = "") -> None:
    ctx = ui_context()
    if not ctx.rich_enabled:
        console.print(message)
        if hint:
            console.print(f"  Hint: {hint}")
        return

    style_map = {
        "info": ctx.theme.info,
        "success": ctx.theme.success,
        "warn": ctx.theme.warning,
        "error": ctx.theme.error,
    }
    style = style_map.get(level, ctx.theme.info)
    title = level.upper()
    body = Text(message, style=style)
    if hint:
        body.append("\n")
        body.append(f"Hint: {hint}", style=ctx.theme.warning)
    console.print(Panel(body, title=title, border_style=style))


def scaffold_created(title: str, path: str, files: list[str], footer: str = "") -> None:
    ctx = ui_context()
    if not ctx.rich_enabled:
        console.print(f"Created {path}")
        for name in files:
            console.print(f"  {name}")
        if footer:
            console.print(footer)
        return

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style=ctx.theme.headline, width=16)
    table.add_column("Value")
    table.add_row("Path", path)
    table.add_row("Files", ", ".join(files))
    if footer:
        table.add_row("Next", footer)
    console.print(Panel(table, title=title, border_style=ctx.theme.success))


def doctor_table(results: list, agent_ok: bool, agent_detail: str, gi_ok: bool) -> None:
    rows: list[tuple[bool, str, str, str]] = []
    rows.append((agent_ok, "agent", agent_detail, "" if agent_ok else "Set agent.native=true"))
    for r in results:
        rows.append((bool(r.ok), str(r.name), str(r.detail), str(r.hint or "")))
    if not gi_ok:
        rows.append((False, "gitignore", "managed block missing/out of date", "openralph gitignore sync ."))

    fail_rows = [row for row in rows if not row[0]]
    ok_rows = [row for row in rows if row[0]]
    ordered = fail_rows + ok_rows
    fail_count = len(fail_rows)
    total_count = len(rows)

    ctx = ui_context()
    if not ctx.rich_enabled:
        _doctor_plain(ordered, fail_count, total_count)
        return

    table = Table(show_header=True, header_style=ctx.theme.headline)
    table.add_column("Status", width=8)
    table.add_column("Component")
    table.add_column("Detail")
    table.add_column("Next Action", style=ctx.theme.warning)

    for ok, name, detail, hint in ordered:
        table.add_row(status_badge(ok, ctx), name, detail, hint)

    headline = (
        Text(f"System Healthy ({total_count} checks)", style=ctx.theme.success)
        if fail_count == 0
        else Text(f"{fail_count} check(s) need attention", style=ctx.theme.error)
    )
    if fail_count:
        actions = [hint for ok, _n, _d, hint in ordered if (not ok and hint)]
        action_text = "\n".join(f"- {a}" for a in dict.fromkeys(actions))
        body = Table.grid(padding=(0, 0))
        body.add_row(headline)
        if action_text:
            body.add_row(Text("Top actions:", style=ctx.theme.warning))
            body.add_row(Text(action_text, style=ctx.theme.warning))
        body.add_row(table)
        console.print(Panel(body, title="Doctor", border_style=ctx.theme.error))
        return

    console.print(Panel(table, title="Doctor", border_style=ctx.theme.success))


def _doctor_plain(rows: list[tuple[bool, str, str, str]], fail_count: int, total_count: int) -> None:
    if fail_count == 0:
        console.print(f"System Healthy ({total_count} checks)")
    else:
        console.print(f"{fail_count} check(s) need attention")

    for ok, name, detail, hint in rows:
        if ok:
            console.print(f"OK {name} - {detail}")
            continue
        console.print(f"FAIL {name} - {detail}")
        if hint:
            console.print(f"  Hint: {hint}")


def config_table(settings_dict: dict, global_path, repo_path) -> None:
    ctx = ui_context()
    if not ctx.rich_enabled:
        console.print("Config paths")
        console.print(f"  Global: {global_path}")
        console.print(f"  Repo:   {repo_path}")
        console.print(json.dumps(settings_dict, indent=2))
        return

    console.print(kv_panel("Config Paths", [("Global", str(global_path)), ("Repo", str(repo_path))], ctx))
    for section, values in settings_dict.items():
        table = Table(show_header=True, header_style=ctx.theme.headline, title=section)
        table.add_column("Key")
        table.add_column("Value")
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, dict):
                    for nested_key, nested_val in value.items():
                        table.add_row(f"{key}.{nested_key}", str(nested_val))
                else:
                    table.add_row(key, str(value))
        else:
            table.add_row(section, str(values))
        console.print(table)


def feature_table(features: list) -> None:
    ctx = ui_context()
    if not ctx.rich_enabled:
        for feat in features:
            marker = "* " if feat.is_current else "  "
            console.print(f"{marker}{feat.date_str} {feat.title}")
            console.print(f"    {feat.path}")
        return

    table = Table(show_header=True, header_style=ctx.theme.headline)
    table.add_column("Current", width=8)
    table.add_column("Date")
    table.add_column("Title")
    table.add_column("Path", style=ctx.theme.muted)
    for feat in features:
        marker = Text("*", style=ctx.theme.accent_primary) if feat.is_current else Text("")
        table.add_row(marker, feat.date_str, feat.title, str(feat.path))
    console.print(Panel(table, title="Features", border_style=ctx.theme.border))


def proxy_panel(title: str, **kwargs: str) -> None:
    ctx = ui_context()
    pairs = [(k, v) for k, v in kwargs.items()]
    if not ctx.rich_enabled:
        console.print(title)
        for k, v in pairs:
            console.print(f"  {k}: {v}")
        return
    console.print(kv_panel(title, pairs, ctx))


def memory_results(hits: list) -> None:
    ctx = ui_context()
    if not hits:
        console.print("No results found.")
        return

    if not ctx.rich_enabled:
        for h in hits:
            console.print(f"{h.path}#{h.chunk_index} score={h.score:.3f}")
            console.print(h.content[:800])
            console.print()
        return

    legend_rows = [("0.70+", "high"), ("0.40-0.69", "medium"), ("<0.40", "low")]
    console.print(Panel(metric_table(legend_rows, ctx), title="Confidence Legend", border_style=ctx.theme.border))

    for h in hits:
        score = h.score
        if score >= 0.7:
            score_style = ctx.theme.success
        elif score >= 0.4:
            score_style = ctx.theme.warning
        else:
            score_style = ctx.theme.error
        subtitle = Text(f"score={score:.3f}", style=score_style)
        console.print(
            Panel(
                h.content[:800],
                title=f"{h.path}#{h.chunk_index}",
                subtitle=subtitle,
                border_style=ctx.theme.border,
            )
        )


def init_results_panel(results: list[tuple[str, str, str]]) -> None:
    ctx = ui_context()

    phases = {
        "repo": [],
        "environment": [],
        "tooling": [],
        "runtime": [],
    }

    for status, name, detail in results:
        bucket = "runtime"
        if name in ("git", "gitignore"):
            bucket = "repo"
        elif name in ("venv", "log"):
            bucket = "environment"
        elif name in ("node", "npm", "python", "ollama", "embedding-model"):
            bucket = "tooling"
        phases[bucket].append((status, name, detail))

    fail_count = sum(1 for status, _name, _detail in results if status == "fail")
    warn_count = sum(1 for status, _name, _detail in results if status == "warn")
    ok_count = sum(1 for status, _name, _detail in results if status == "ok")
    total = len(results)

    if not ctx.rich_enabled:
        summary = f"Init summary: ok={ok_count}, warn={warn_count}, fail={fail_count}, total={total}"
        console.print(summary)
        for phase, items in phases.items():
            if not items:
                continue
            console.print(f"[{phase}]")
            for status, name, detail in items:
                console.print(f"  {status.upper()} {name} - {detail}")
        return

    grid = Table.grid(expand=True)
    summary_rows = [
        ("OK", str(ok_count)),
        ("WARN", str(warn_count)),
        ("FAIL", str(fail_count)),
        ("Total", str(total)),
    ]
    grid.add_row(Panel(metric_table(summary_rows, ctx), title="Init Summary", border_style=ctx.theme.border))
    for phase, items in phases.items():
        if not items:
            continue
        ordered_items = sorted(items, key=lambda item: {"fail": 0, "warn": 1, "ok": 2}.get(item[0], 3))
        table = Table(show_header=True, header_style=ctx.theme.headline)
        table.add_column("Status", width=8)
        table.add_column("Component")
        table.add_column("Detail")
        for status, name, detail in ordered_items:
            if status == "ok":
                badge = status_badge(True, ctx)
            elif status == "warn":
                badge = status_badge(False, ctx, warn=True)
            else:
                badge = status_badge(False, ctx)
            table.add_row(badge, name, detail)
        grid.add_row(Panel(table, title=f"Init: {phase.title()}", border_style=ctx.theme.border))

    console.print(grid)
