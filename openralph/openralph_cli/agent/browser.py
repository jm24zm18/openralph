from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json
import re


@dataclass(frozen=True)
class BrowserSessionConfig:
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    default_timeout: int = 10000
    console_buffer_max: int = 500
    network_buffer_max: int = 200
    screenshot_dir: Path = Path(".ralph/screenshots")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BrowserSession:
    def __init__(self, config: BrowserSessionConfig) -> None:
        self.config = config
        self._lock = Lock()
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._console_log: list[dict[str, Any]] = []
        self._network_log: list[dict[str, Any]] = []
        self._error_log: list[dict[str, Any]] = []
        self._crashed = False

    def ensure_started(self) -> None:
        with self._lock:
            self._ensure_started_locked()

    def _ensure_started_locked(self) -> None:
        if self._page is not None and not self._page.is_closed() and not self._crashed:
            return
        self._start_locked()

    def _start_locked(self) -> None:
        self._stop_locked()
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError(_playwright_install_hint(f"{type(e).__name__}: {e}")) from e

        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.config.headless)
        self._context = self._browser.new_context(
            viewport={
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            }
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.config.default_timeout)
        self._register_page_handlers_locked(self._page)
        self._crashed = False

    def _stop_locked(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def close(self) -> None:
        with self._lock:
            self._stop_locked()

    def _register_page_handlers_locked(self, page: Any) -> None:
        def on_console(msg: Any) -> None:
            self._append_ring(
                self._console_log,
                {
                    "type": msg.type,
                    "text": msg.text,
                    "url": page.url or "",
                    "timestamp": _utc_now(),
                },
                self.config.console_buffer_max,
            )

        def on_pageerror(err: Any) -> None:
            self._append_ring(
                self._error_log,
                {
                    "message": str(err),
                    "url": page.url or "",
                    "timestamp": _utc_now(),
                },
                self.config.console_buffer_max,
            )

        def on_response(resp: Any) -> None:
            req = resp.request
            ctype = ""
            try:
                ctype = resp.headers.get("content-type", "")
            except Exception:
                ctype = ""
            status = None
            try:
                status = int(resp.status)
            except Exception:
                status = None
            self._append_ring(
                self._network_log,
                {
                    "method": str(req.method),
                    "url": str(resp.url),
                    "status": status,
                    "content_type": ctype,
                    "timestamp": _utc_now(),
                },
                self.config.network_buffer_max,
            )

        def on_crash() -> None:
            self._crashed = True

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)
        page.on("crash", on_crash)

    def _append_ring(self, target: list[dict[str, Any]], event: dict[str, Any], limit: int) -> None:
        target.append(event)
        overflow = len(target) - max(1, limit)
        if overflow > 0:
            del target[:overflow]

    def _with_recovery(self, fn: Any, *, action: str) -> Any:
        with self._lock:
            self._ensure_started_locked()
            try:
                return fn(self._page)
            except Exception as e:
                msg = str(e).lower()
                recoverable = any(token in msg for token in ("closed", "target page", "crash"))
                if not recoverable:
                    raise
                self._start_locked()
                raise RuntimeError(
                    f"Browser session restarted after {action} failure. Run browser_navigate again."
                ) from e

    def navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict[str, Any]:
        allowed = {"commit", "domcontentloaded", "load", "networkidle"}
        mode = wait_until if wait_until in allowed else "domcontentloaded"
        res = self._with_recovery(
            lambda p: p.goto(url, wait_until=mode),
            action="navigate",
        )
        status = None
        if res is not None:
            try:
                status = int(res.status)
            except Exception:
                status = None
        title = self._with_recovery(lambda p: p.title(), action="read title")
        current_url = self._with_recovery(lambda p: p.url, action="read url")
        return {"url": current_url, "title": title, "status": status}

    def click(self, selector: str) -> dict[str, Any]:
        self._with_recovery(lambda p: p.click(selector), action="click")
        current_url = self._with_recovery(lambda p: p.url, action="read url")
        return {"ok": True, "selector": selector, "url": current_url}

    def fill(self, selector: str, value: str) -> dict[str, Any]:
        self._with_recovery(lambda p: p.fill(selector, value), action="fill")
        return {"ok": True, "selector": selector}

    def type_text(self, selector: str, value: str, delay_ms: int = 0) -> dict[str, Any]:
        self._with_recovery(lambda p: p.fill(selector, ""), action="clear")
        self._with_recovery(lambda p: p.type(selector, value, delay=delay_ms), action="type")
        return {"ok": True, "selector": selector}

    def press(self, selector: str, key: str) -> dict[str, Any]:
        self._with_recovery(lambda p: p.press(selector, key), action="press")
        return {"ok": True, "selector": selector, "key": key}

    def screenshot(self, full_page: bool = False, name: str | None = None) -> dict[str, Any]:
        stem = (name or f"screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}").strip()
        safe = re.sub(r"[^a-zA-Z0-9._-]", "-", stem)[:80] or "screenshot"
        path = self.config.screenshot_dir / f"{safe}.png"
        self._with_recovery(lambda p: p.screenshot(path=str(path), full_page=full_page), action="screenshot")
        snapshot = self.snapshot()
        return {"path": str(path), "snapshot": snapshot}

    def snapshot(self) -> dict[str, Any]:
        return self._with_recovery(
            lambda p: (p.accessibility.snapshot() or {}),
            action="snapshot",
        )

    def evaluate(self, expression: str) -> Any:
        return self._with_recovery(lambda p: p.evaluate(expression), action="evaluate")

    def wait_for_selector(self, selector: str, timeout_ms: int | None = None) -> dict[str, Any]:
        timeout = timeout_ms if timeout_ms is not None else self.config.default_timeout
        self._with_recovery(lambda p: p.wait_for_selector(selector, timeout=timeout), action="wait_for_selector")
        return {"ok": True, "selector": selector}

    def get_url(self) -> str:
        return self._with_recovery(lambda p: p.url, action="read url")

    def get_content(self) -> str:
        return self._with_recovery(lambda p: p.content(), action="read content")

    def get_console(self, level: str | None = None, last_n: int = 50, clear: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._console_log)
            if level:
                normalized = level.strip().lower()
                rows = [r for r in rows if str(r.get("type", "")).lower() == normalized]
            if last_n > 0:
                rows = rows[-last_n:]
            if clear:
                self._console_log.clear()
            return rows

    def get_network(
        self,
        method: str | None = None,
        status_filter: str | None = None,
        last_n: int = 50,
        clear: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._network_log)
            if method:
                m = method.strip().upper()
                rows = [r for r in rows if str(r.get("method", "")).upper() == m]
            if status_filter:
                sf = status_filter.strip()
                if sf.endswith("xx") and len(sf) == 3 and sf[0].isdigit():
                    prefix = sf[0]
                    rows = [r for r in rows if str(r.get("status", "")).startswith(prefix)]
                elif sf.isdigit():
                    rows = [r for r in rows if str(r.get("status", "")) == sf]
            if last_n > 0:
                rows = rows[-last_n:]
            if clear:
                self._network_log.clear()
            return rows

    def get_errors(self, last_n: int = 50, clear: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._error_log[-last_n:] if last_n > 0 else list(self._error_log)
            if clear:
                self._error_log.clear()
            return rows


def _playwright_install_hint(detail: str) -> str:
    return (
        "Playwright Python runtime is unavailable. "
        "Install with `python3 -m pip install playwright` and "
        "`python3 -m playwright install chromium`. "
        f"Detail: {detail}"
    )


def _session_key(config: BrowserSessionConfig) -> tuple[Any, ...]:
    return (
        config.headless,
        config.viewport_width,
        config.viewport_height,
        config.default_timeout,
        config.console_buffer_max,
        config.network_buffer_max,
        str(config.screenshot_dir.resolve()),
    )


_SESSION_LOCK = Lock()
_SESSION: BrowserSession | None = None
_SESSION_KEY: tuple[Any, ...] | None = None


def get_session(config: BrowserSessionConfig) -> BrowserSession:
    global _SESSION
    global _SESSION_KEY

    key = _session_key(config)
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = BrowserSession(config=config)
            _SESSION_KEY = key
        elif _SESSION_KEY != key:
            _SESSION.close()
            _SESSION = BrowserSession(config=config)
            _SESSION_KEY = key
        return _SESSION


def close_session() -> None:
    global _SESSION
    global _SESSION_KEY
    with _SESSION_LOCK:
        if _SESSION is not None:
            _SESSION.close()
        _SESSION = None
        _SESSION_KEY = None


def to_pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
