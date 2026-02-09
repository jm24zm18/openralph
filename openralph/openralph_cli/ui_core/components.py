from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .context import UIContext
from .theme import GLYPHS


def status_badge(ok: bool, ctx: UIContext, warn: bool = False) -> Text:
    if warn:
        return Text("WARN", style=ctx.theme.warning)
    if ok:
        return Text("OK", style=ctx.theme.success)
    return Text("FAIL", style=ctx.theme.error)


def stage_pipeline(current: str, ctx: UIContext, stages: list[str]) -> Text:
    text = Text()
    current_index = stages.index(current) if current in stages else -1
    for idx, stage in enumerate(stages):
        if idx > 0:
            text.append(" -> ", style=ctx.theme.muted)

        if idx < current_index:
            label = f"{GLYPHS.stage_done} {stage.title()}"
            text.append(label, style=ctx.theme.muted)
        elif idx == current_index:
            label = f"{GLYPHS.stage_active} {stage.title()}"
            text.append(label, style=ctx.theme.accent_primary)
        else:
            label = f"{GLYPHS.stage_pending} {stage.title()}"
            text.append(label, style=ctx.theme.muted)
    return text


def metric_table(rows: list[tuple[str, str]], ctx: UIContext) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style=ctx.theme.headline)
    table.add_column("Value")
    for k, v in rows:
        table.add_row(k, v)
    return table


def kv_panel(title: str, values: list[tuple[str, str]], ctx: UIContext) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style=ctx.theme.headline)
    table.add_column("Value")
    for k, v in values:
        table.add_row(k, v)
    return Panel(table, title=title, border_style=ctx.theme.border)
