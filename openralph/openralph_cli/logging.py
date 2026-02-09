from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}
_initialized: bool = False
_log_file_path: Optional[Path] = None
_log_level: int = logging.INFO
_console_enabled: bool = True
_raw_debug_enabled: bool = False
_raw_log_files: dict[str, Optional[Path]] = {"provider": None, "tools": None}
_raw_lock = threading.Lock()


@dataclass(frozen=True)
class LogConfig:
    level: str = "INFO"
    console: bool = True
    file: bool = True
    raw_debug: bool = False
    file_path: Optional[Path] = None
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"


def _level_from_str(level: str) -> int:
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return levels.get(level.upper(), logging.INFO)


class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        original = super().format(record)
        if color and sys.stderr.isatty():
            return f"{color}{original}{self.RESET}"
        return original


def init_logging(config: LogConfig, log_dir: Optional[Path] = None) -> None:
    global _initialized, _log_file_path, _log_level, _console_enabled, _raw_debug_enabled, _raw_log_files

    if _initialized:
        return

    _log_level = _level_from_str(config.level)
    _console_enabled = config.console
    _raw_debug_enabled = bool(config.raw_debug)
    _raw_log_files = {"provider": None, "tools": None}

    root_logger = logging.getLogger("openralph")
    root_logger.setLevel(_log_level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(config.format, datefmt=config.date_format)

    if config.console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(_log_level)
        console_handler.setFormatter(ColoredFormatter(config.format, datefmt=config.date_format))
        root_logger.addHandler(console_handler)

    if config.file and log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if config.file_path:
            _log_file_path = config.file_path
        else:
            _log_file_path = log_dir / f"openralph_{timestamp}.log"
        file_handler = logging.FileHandler(_log_file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        if _raw_debug_enabled:
            _raw_log_files["provider"] = log_dir / f"raw_provider_{timestamp}.log"
            _raw_log_files["tools"] = log_dir / f"raw_tools_{timestamp}.log"

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    full_name = f"openralph.{name}" if not name.startswith("openralph") else name
    logger = logging.getLogger(full_name)
    _loggers[name] = logger
    return logger


def get_log_file() -> Optional[Path]:
    return _log_file_path


def raw_debug_enabled() -> bool:
    return _raw_debug_enabled


def get_raw_log_file(channel: str) -> Optional[Path]:
    return _raw_log_files.get(channel)


def raw_log(channel: str, payload: str) -> None:
    if not _raw_debug_enabled:
        return
    target = _raw_log_files.get(channel)
    if target is None:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n===== {stamp} [{channel}] =====\n{payload}\n"
    try:
        with _raw_lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(block)
    except OSError:
        # Raw logs are best-effort and should never break normal execution.
        return


def reset_logging() -> None:
    global _initialized, _log_file_path, _loggers, _raw_debug_enabled, _raw_log_files
    _initialized = False
    _log_file_path = None
    _raw_debug_enabled = False
    _raw_log_files = {"provider": None, "tools": None}
    _loggers.clear()
    root_logger = logging.getLogger("openralph")
    root_logger.handlers.clear()


# Convenience function for quick debug logging without full init
def quick_debug(name: str, msg: str, *args: object) -> None:
    logger = get_logger(name)
    logger.debug(msg, *args)


# Context manager for temporarily changing log level
class log_level_context:
    def __init__(self, level: str):
        self.level = _level_from_str(level)
        self.old_level: Optional[int] = None

    def __enter__(self) -> "log_level_context":
        root_logger = logging.getLogger("openralph")
        self.old_level = root_logger.level
        root_logger.setLevel(self.level)
        for handler in root_logger.handlers:
            handler.setLevel(self.level)
        return self

    def __exit__(self, *args: object) -> None:
        if self.old_level is not None:
            root_logger = logging.getLogger("openralph")
            root_logger.setLevel(self.old_level)
            for handler in root_logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.setLevel(logging.DEBUG)
                else:
                    handler.setLevel(self.old_level)
