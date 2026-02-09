from __future__ import annotations

import os
from dataclasses import dataclass

from rich.console import Console

from .theme import UITheme, get_theme


console = Console()

_FORCE_PLAIN: bool | None = None
_FORCE_STYLE: str | None = None


@dataclass(frozen=True)
class UIContext:
    rich_enabled: bool
    style: str
    theme: UITheme
    width: int


def set_cli_ui_overrides(plain: bool | None, style: str | None) -> None:
    global _FORCE_PLAIN, _FORCE_STYLE
    _FORCE_PLAIN = plain
    _FORCE_STYLE = style


def ui_context() -> UIContext:
    forced_style = _FORCE_STYLE or "signature"
    env_plain = os.environ.get("OPENRALPH_NO_UI", "") == "1"
    ci = os.environ.get("CI", "").lower() == "true"
    forced_plain = _FORCE_PLAIN is True

    rich_enabled = console.is_terminal and not env_plain and not ci and not forced_plain
    width = int(getattr(console.size, "width", 120) or 120)

    return UIContext(
        rich_enabled=rich_enabled,
        style=forced_style,
        theme=get_theme(forced_style),
        width=width,
    )
