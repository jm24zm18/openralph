from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.columns import Columns
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .components import metric_table, stage_pipeline
from .context import console, ui_context
from .events import EventBuffer
from .theme import GLYPHS


_STAGES = ["setup", "builder", "test", "review", "gate"]


@dataclass
class DashboardState:
    feature_index: int = 0
    feature_total: int = 0
    feature_slug: str = ""
    iteration: int = 0
    max_iterations: int = 0
    stage: str = "setup"
    turn: int = 0
    recent_tools: list[str] = field(default_factory=list)
    gate_history: list[tuple[int, bool]] = field(default_factory=list)
    tool_calls: int = 0
    tool_errors: int = 0
    start_time: float = field(default_factory=time.monotonic)
    events: EventBuffer = field(default_factory=lambda: EventBuffer(max_events=100))


class Dashboard:
    def __init__(self) -> None:
        self.state = DashboardState()
        self._live: Live | None = None

    def start(self) -> None:
        ctx = ui_context()
        if not ctx.rich_enabled:
            return
        self._live = Live(self._render(), console=console, refresh_per_second=4, transient=True)
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def set_feature(self, index: int, total: int, slug: str) -> None:
        self.state.feature_index = index
        self.state.feature_total = total
        self.state.feature_slug = slug
        self.state.iteration = 0
        self.state.stage = "setup"
        self.state.recent_tools = []
        self.state.events.add("info", "feature", f"{index}/{total} {slug}")
        self._refresh()

    def set_iteration(self, iteration: int, max_iterations: int) -> None:
        self.state.iteration = iteration
        self.state.max_iterations = max_iterations
        self.state.stage = "builder"
        self.state.turn = 0
        self.state.recent_tools = []
        self.state.events.add("info", "iteration", f"{iteration}/{max_iterations}")
        self._refresh()

    def set_stage(self, stage: str) -> None:
        self.state.stage = stage
        self.state.events.add("info", "stage", stage)
        self._refresh()

    def set_turn(self, turn: int) -> None:
        self.state.turn = turn
        self._refresh()

    def add_event(self, severity: str, source: str, message: str) -> None:
        self.state.events.add(severity, source, message)
        self._refresh()

    def add_tool_call(self, name: str, args_brief: str) -> None:
        self.state.tool_calls += 1
        entry = f"{name}: {args_brief}" if args_brief else name
        self.state.recent_tools.append(entry)
        if len(self.state.recent_tools) > 8:
            self.state.recent_tools = self.state.recent_tools[-8:]
        self.state.events.add("info", "tool", entry)
        self._refresh()

    def add_tool_result(self, name: str, ok: bool, summary: str = "") -> None:
        if not ok:
            self.state.tool_errors += 1
        details = f"{name} {summary}".strip()
        severity = "success" if ok else "error"
        self.state.events.add(severity, "tool", details)
        self._refresh()

    def add_tool_error(self) -> None:
        self.state.tool_errors += 1
        self.state.events.add("error", "tool", "tool execution failed")
        self._refresh()

    def record_gate(self, iteration: int, passed: bool) -> None:
        self.state.gate_history.append((iteration, passed))
        severity = "success" if passed else "error"
        self.state.events.add(severity, "gate", f"iteration {iteration}: {'PASS' if passed else 'FAIL'}")
        self._refresh()

    def _render(self) -> Panel:
        ctx = ui_context()
        s = self.state

        elapsed = _format_elapsed(s.start_time)
        stages = stage_pipeline(s.stage, ctx, _STAGES)

        top_rows: list[tuple[str, str]] = []
        if s.feature_total > 0:
            top_rows.append(("Feature", f"{s.feature_index}/{s.feature_total} {s.feature_slug}"))
        if s.iteration > 0:
            top_rows.append(("Iteration", f"{s.iteration}/{s.max_iterations}"))
        top_rows.append(("Elapsed", elapsed))
        top_rows.append(("Turn", str(s.turn)))

        stats_rows = [
            ("Tool calls", str(s.tool_calls)),
            ("Tool errors", str(s.tool_errors)),
            ("Gate trend", _gate_trend(s.gate_history)),
            ("Gate checks", str(len(s.gate_history))),
        ]

        compact = ctx.width < 100
        ultra_compact = ctx.width < 85
        events_count = 6 if ultra_compact else 8 if compact else 10

        stage_title = "Stage" if ultra_compact else "Stage Rail"
        tools_title = "Tools" if ultra_compact else "Recent Tools"
        events_title = "Events" if ultra_compact else "Event Feed"

        stage_panel = Panel(stages, title=stage_title, border_style=ctx.theme.border)
        metrics_panel = Panel(metric_table(top_rows + stats_rows, ctx), title="Telemetry", border_style=ctx.theme.border)
        tools_panel = Panel(_recent_tools_table(s.recent_tools, ctx), title=tools_title, border_style=ctx.theme.border)
        events_panel = Panel(_events_table(s.events.latest(events_count), ctx), title=events_title, border_style=ctx.theme.border)

        if ultra_compact:
            combined = Table.grid(padding=(0, 0))
            combined.add_row(stage_panel)
            combined.add_row(metrics_panel)
            combined.add_row(events_panel)
        elif compact:
            body = Columns([stage_panel, metrics_panel], expand=True)
            combined = Table.grid(padding=(0, 0))
            combined.add_row(body)
            combined.add_row(tools_panel)
            combined.add_row(events_panel)
        else:
            combined = Columns([stage_panel, metrics_panel, tools_panel, events_panel], expand=True)

        return Panel(combined, title="OPENRALPH // LIVE RUN", subtitle=f"style={ctx.style}", border_style=ctx.theme.border)


def _events_table(events, ctx) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("S", width=1)
    source_width = 6 if ctx.width < 85 else 8
    table.add_column("Source", width=source_width, style=ctx.theme.muted)
    table.add_column("Message")
    for ev in events:
        glyph, style = _event_style(ev.severity, ctx)
        table.add_row(
            glyph,
            _truncate(ev.source, source_width),
            Text(_truncate(ev.message, _event_message_width(ctx.width)), style=style),
        )
    return table


def _recent_tools_table(recent_tools: list[str], ctx) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Tool", style=ctx.theme.accent_secondary)
    items = recent_tools[-8:] if recent_tools else ["(no tool activity yet)"]
    for item in items:
        table.add_row(_truncate(item, _tool_line_width(ctx.width)))
    return table


def _gate_trend(history: list[tuple[int, bool]]) -> str:
    if not history:
        return "-"
    markers = ["P" if ok else "F" for _, ok in history[-12:]]
    return "".join(markers)


def _event_style(severity: str, ctx) -> tuple[str, str]:
    if severity == "success":
        return GLYPHS.event_success, ctx.theme.success
    if severity == "warn":
        return GLYPHS.event_warning, ctx.theme.warning
    if severity == "error":
        return GLYPHS.event_error, ctx.theme.error
    return GLYPHS.event_info, ctx.theme.info


def _truncate(text: str, limit: int) -> str:
    if limit <= 3 or len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _tool_line_width(width: int) -> int:
    if width < 85:
        return 28
    if width < 100:
        return 48
    return 80


def _event_message_width(width: int) -> int:
    if width < 85:
        return 28
    if width < 100:
        return 42
    return 64


def _format_elapsed(start: float) -> str:
    elapsed = time.monotonic() - start
    mins, secs = divmod(int(elapsed), 60)
    if mins:
        return f"{mins}m {secs:02d}s"
    return f"{secs}s"


def run_summary(state: DashboardState) -> None:
    ctx = ui_context()
    elapsed = _format_elapsed(state.start_time)
    rows = [
        ("Duration", elapsed),
        ("Tool calls", str(state.tool_calls)),
        ("Tool errors", str(state.tool_errors)),
    ]
    if state.gate_history:
        passes = sum(1 for _, ok in state.gate_history if ok)
        fails = sum(1 for _, ok in state.gate_history if not ok)
        rows.append(("Gate passes", str(passes)))
        rows.append(("Gate fails", str(fails)))
    if state.feature_total > 0:
        rows.append(("Features", f"{state.feature_index}/{state.feature_total}"))

    final_gate = state.gate_history[-1] if state.gate_history else None
    if final_gate and final_gate[1] and state.tool_errors > 0:
        title = "Run Complete - PASS WITH WARNINGS"
        border = ctx.theme.warning
    elif final_gate and final_gate[1]:
        title = "Run Complete - PASS"
        border = ctx.theme.success
    else:
        title = "Run Complete"
        border = ctx.theme.error

    if not ctx.rich_enabled:
        console.print(f"{title} ({elapsed})")
        for k, v in rows:
            console.print(f"  {k}: {v}")
        return

    panel = Panel(metric_table(rows, ctx), title=title, border_style=border)
    console.print(panel)
