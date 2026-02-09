from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UITheme:
    name: str
    headline: str
    accent_primary: str
    accent_secondary: str
    success: str
    warning: str
    error: str
    muted: str
    border: str
    info: str


@dataclass(frozen=True)
class UIGlyphs:
    stage_active: str
    stage_done: str
    stage_pending: str
    event_info: str
    event_success: str
    event_warning: str
    event_error: str


SIGNATURE_THEME = UITheme(
    name="signature",
    headline="bold #ffd166",
    accent_primary="bold #00d1b2",
    accent_secondary="#4cc9f0",
    success="bold #3ddc97",
    warning="bold #ffb703",
    error="bold #ef476f",
    muted="#7f8c8d",
    border="#2a9d8f",
    info="#4cc9f0",
)

MINIMAL_THEME = UITheme(
    name="minimal",
    headline="bold",
    accent_primary="bold cyan",
    accent_secondary="cyan",
    success="green",
    warning="yellow",
    error="red",
    muted="dim",
    border="blue",
    info="cyan",
)

GLYPHS = UIGlyphs(
    stage_active=">",
    stage_done="*",
    stage_pending="~",
    event_info="i",
    event_success="+",
    event_warning="!",
    event_error="x",
)


def get_theme(style: str) -> UITheme:
    if style == "minimal":
        return MINIMAL_THEME
    return SIGNATURE_THEME
