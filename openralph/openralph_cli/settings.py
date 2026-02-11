from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import sys

try:
    import tomllib  # py>=3.11
except Exception:
    import tomli as tomllib  # type: ignore


class ConfigLoadError(RuntimeError):
    def __init__(self, message: str, *, path: Path | None = None, key_path: str = "") -> None:
        super().__init__(message)
        self.path = path
        self.key_path = key_path


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ConfigLoadError(f"TOML parse error: {e}", path=path) from e
    if not isinstance(data, dict):
        raise ConfigLoadError("Top-level TOML content must be a table/object", path=path)
    return data


def _nested_key_exists(data: dict, keys: tuple[str, ...]) -> bool:
    cur: object = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    return True


def _ensure_table(raw: dict, section: str, *, source: Path | None) -> dict:
    value = raw.get(section, {})
    if not isinstance(value, dict):
        raise ConfigLoadError(
            f"'{section}' must be a table/object",
            path=source,
            key_path=section,
        )
    return value


def _to_int(value: object, *, key_path: str, source: Path | None) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ConfigLoadError(
            f"'{key_path}' must be an integer (got {value!r})",
            path=source,
            key_path=key_path,
        ) from e


def _to_float(value: object, *, key_path: str, source: Path | None) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ConfigLoadError(
            f"'{key_path}' must be a number (got {value!r})",
            path=source,
            key_path=key_path,
        ) from e


def _to_bool(value: object, *, key_path: str, source: Path | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigLoadError(
        f"'{key_path}' must be a boolean (got {value!r})",
        path=source,
        key_path=key_path,
    )


def _to_str(value: object, *, key_path: str, source: Path | None) -> str:
    if isinstance(value, str):
        return value
    raise ConfigLoadError(
        f"'{key_path}' must be a string (got {value!r})",
        path=source,
        key_path=key_path,
    )


def _to_str_list(value: object, *, key_path: str, source: Path | None) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                raise ConfigLoadError(
                    f"'{key_path}[{idx}]' must be a string (got {item!r})",
                    path=source,
                    key_path=key_path,
                )
            out.append(item)
        return out
    raise ConfigLoadError(
        f"'{key_path}' must be a list of strings (got {value!r})",
        path=source,
        key_path=key_path,
    )


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[7:].strip()
    if "=" not in text:
        return None
    key, value = text.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if value and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    else:
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
    return key, value


def _load_repo_dotenv(repo: Path) -> None:
    env_path = repo / ".env"
    if not env_path.exists() or not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            item = _parse_dotenv_line(line)
            if not item:
                continue
            key, value = item
            # Keep real environment vars highest priority.
            os.environ.setdefault(key, value)
    except Exception:
        # Best effort only: never block CLI execution on .env parsing.
        return


_TOOL_PERMISSION_ALIASES: dict[str, str] = {
    "edit": "edit_file",
    "read": "read_file",
    "write": "write_file",
    "search_repo": "repo_search",
    "ls": "list_dir",
    "navigate": "browser_navigate",
    "js_eval": "browser_evaluate",
    "console": "browser_console",
    "network": "browser_network",
}

_VALID_AGENT_TOOL_PERMISSIONS = {
    "bash",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "list_dir",
    "search",
    "repo_search",
    "browser_navigate",
    "browser_click",
    "browser_fill",
    "browser_screenshot",
    "browser_snapshot",
    "browser_evaluate",
    "browser_console",
    "browser_network",
}


def _normalize_agent_permissions(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        name = str(raw).strip()
        if not name:
            continue
        mapped = _TOOL_PERMISSION_ALIASES.get(name, name)
        if mapped in _VALID_AGENT_TOOL_PERMISSIONS and mapped not in normalized:
            normalized.append(mapped)
    return normalized

def global_config_path() -> Path:
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "openralph" / "config.toml"
    return Path.home() / ".config" / "openralph" / "config.toml"

def repo_config_path(repo: Path) -> Path:
    return repo.resolve() / ".openralph.toml"

@dataclass
class OpenRalphSettings:
    # Ollama
    ollama_host: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"

    # Init
    init_install_tools: bool = True
    init_node_tooling: str = "global"  # global|local
    init_create_venv: bool = False
    init_playwright: bool = True
    init_playwright_browsers: bool = True
    init_playwright_cli: bool = True

    # Loop
    loop_max_iters: int = 10
    loop_rollback_on_gate_fail: bool = False
    loop_max_gate_fails: int = 5
    loop_prd_refresh_every: int = 0
    loop_prd_refresh_mode: str = ""  # "" | "ask"
    loop_prd_qa_mode: str = "handoff"  # interactive|handoff|auto|auto-then-handoff
    loop_test_report: str = ".ralph/TEST_REPORT.md"
    loop_review_report: str = ".ralph/REVIEW_REPORT.md"
    loop_final_report: str = ".ralph/FINAL.md"
    loop_auto_mode: str = ""  # "" (off) | "full" (PRD+plan+build all features)
    loop_max_feature_iters: int = 8  # Max iterations per feature when auto_mode=full
    loop_retry_failed: bool = True  # Retry failed features on re-run
    loop_smoke_check: bool = True  # Run runtime smoke checks after gate PASS
    loop_smoke_timeout: int = 10  # Per-check subprocess timeout in seconds
    loop_max_tool_errors: int = 0  # Max allowed tool errors before run is downgraded

    # Memory
    memory_k: int = 8
    memory_inject_max_chars: int = 6000
    memory_chunk_chars: int = 1800
    memory_chunk_overlap: int = 200
    memory_vacuum_warn_mb: float = 200.0
    memory_exclude_dirs: list[str] = field(default_factory=lambda: [".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph"])
    memory_include_exts: list[str] = field(default_factory=lambda: [
        ".md", ".mdx", ".markdown", ".txt",
        ".py",
        ".js", ".ts", ".jsx", ".tsx",
        ".html", ".htm",
        ".css", ".scss", ".less",
        ".json", ".jsonc", ".yaml", ".yml", ".toml"
    ])

    # Logging
    log_level: str = "INFO"
    log_console: bool = False  # Don't spam console by default, use Rich output
    log_file: bool = True
    log_raw_debug: bool = True  # Write full untruncated provider/tool payloads to raw logs

    # Sandbox
    sandbox_enabled: bool = True
    sandbox_mode: str = "docker"  # docker|local
    sandbox_docker_image: str = "python:3.12-slim"
    sandbox_network: str = "bridge"  # bridge|none
    sandbox_fail_closed: bool = True
    sandbox_env_allowlist: list[str] = field(default_factory=lambda: ["OLLAMA_HOST", "EMBED_MODEL", "BRAVE_API_KEY"])

    # Browser
    browser_headless: bool = True
    browser_viewport_width: int = 1280
    browser_viewport_height: int = 720
    browser_default_timeout: int = 10000
    browser_console_buffer_max: int = 500
    browser_network_buffer_max: int = 200

    # Proxy
    proxy_enabled: bool = False
    proxy_listen_port: int = 18889
    proxy_target_host: str = "127.0.0.1"
    proxy_target_port: int = 30000
    proxy_target_model: str = "openai/gpt-oss-120b"
    proxy_provider_name: str = "openclaw"
    proxy_provider_display: str = "DGX gpt-OSS"
    proxy_model_id: str = "chatgpt-oss"
    proxy_model_display: str = "ChatGPT-OSS 120B"
    proxy_api_key: str = "LOCAL_DGX"
    proxy_auto_start: bool = True
    proxy_log_requests: bool = False
    proxy_cors_enabled: bool = False
    proxy_cors_allow_origin: str = "*"

    # UI
    ui_dashboard: bool = True

    # Native agent settings
    agent_native: bool = True  # Must remain true; OpenCode support removed
    agent_max_turns: int = 80  # Max tool call iterations per agent run
    agent_timeout: int = 120  # Per-tool timeout in seconds
    agent_max_output: int = 50000  # Max chars per tool output

    # Agents - all default to proxy provider/model
    agents_enabled: bool = True
    agents_default_provider: str = ""  # empty = use proxy provider
    agents_default_model: str = ""  # empty = use proxy model
    # Per-agent overrides (provider:model format, empty = use default)
    agent_code_model: str = ""
    agent_plan_model: str = ""
    agent_test_model: str = ""
    agent_review_model: str = ""
    # Per-agent permissions
    agent_code_permissions: list[str] = field(default_factory=lambda: [
        "bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search", "search",
        "browser_navigate", "browser_click", "browser_fill", "browser_screenshot", "browser_snapshot",
        "browser_evaluate", "browser_console", "browser_network",
    ])
    agent_plan_permissions: list[str] = field(default_factory=lambda: ["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search"])
    agent_test_permissions: list[str] = field(default_factory=lambda: [
        "bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search",
        "browser_navigate", "browser_click", "browser_fill", "browser_screenshot", "browser_snapshot",
        "browser_evaluate", "browser_console", "browser_network",
    ])
    agent_review_permissions: list[str] = field(default_factory=lambda: ["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search"])

    @staticmethod
    def load(repo: Path) -> "OpenRalphSettings":
        repo = repo.resolve()
        _load_repo_dotenv(repo)
        s = OpenRalphSettings()
        global_path = global_config_path()
        repo_path = repo_config_path(repo)
        g = _load_toml(global_path)
        r = _load_toml(repo_path)
        merged = _deep_merge(g, r)

        def _source_for(*keys: str) -> Path | None:
            key_path = tuple(keys)
            if _nested_key_exists(r, key_path):
                return repo_path
            if _nested_key_exists(g, key_path):
                return global_path
            return None

        if os.environ.get("OLLAMA_HOST"):
            merged.setdefault("ollama", {})
            merged["ollama"]["host"] = os.environ["OLLAMA_HOST"]
        if os.environ.get("EMBED_MODEL"):
            merged.setdefault("ollama", {})
            merged["ollama"]["embed_model"] = os.environ["EMBED_MODEL"]

        oll = _ensure_table(merged, "ollama", source=_source_for("ollama"))
        s.ollama_host = _to_str(oll.get("host", s.ollama_host), key_path="ollama.host", source=_source_for("ollama", "host"))
        s.embed_model = _to_str(oll.get("embed_model", s.embed_model), key_path="ollama.embed_model", source=_source_for("ollama", "embed_model"))

        ini = _ensure_table(merged, "init", source=_source_for("init"))
        s.init_install_tools = _to_bool(ini.get("install_tools", s.init_install_tools), key_path="init.install_tools", source=_source_for("init", "install_tools"))
        s.init_node_tooling = _to_str(ini.get("node_tooling", s.init_node_tooling), key_path="init.node_tooling", source=_source_for("init", "node_tooling"))
        s.init_create_venv = _to_bool(ini.get("create_venv", s.init_create_venv), key_path="init.create_venv", source=_source_for("init", "create_venv"))
        s.init_playwright = _to_bool(ini.get("playwright", s.init_playwright), key_path="init.playwright", source=_source_for("init", "playwright"))
        s.init_playwright_browsers = _to_bool(ini.get("playwright_browsers", s.init_playwright_browsers), key_path="init.playwright_browsers", source=_source_for("init", "playwright_browsers"))
        s.init_playwright_cli = _to_bool(ini.get("playwright_cli", s.init_playwright_cli), key_path="init.playwright_cli", source=_source_for("init", "playwright_cli"))

        loop = _ensure_table(merged, "loop", source=_source_for("loop"))
        s.loop_max_iters = _to_int(loop.get("max_iters", s.loop_max_iters), key_path="loop.max_iters", source=_source_for("loop", "max_iters"))
        s.loop_rollback_on_gate_fail = _to_bool(loop.get("rollback_on_gate_fail", s.loop_rollback_on_gate_fail), key_path="loop.rollback_on_gate_fail", source=_source_for("loop", "rollback_on_gate_fail"))
        s.loop_max_gate_fails = _to_int(loop.get("max_gate_fails", s.loop_max_gate_fails), key_path="loop.max_gate_fails", source=_source_for("loop", "max_gate_fails"))
        s.loop_prd_refresh_every = _to_int(loop.get("prd_refresh_every", s.loop_prd_refresh_every), key_path="loop.prd_refresh_every", source=_source_for("loop", "prd_refresh_every"))
        s.loop_prd_refresh_mode = _to_str(loop.get("prd_refresh_mode", s.loop_prd_refresh_mode), key_path="loop.prd_refresh_mode", source=_source_for("loop", "prd_refresh_mode")) or ""
        s.loop_prd_qa_mode = _to_str(loop.get("prd_qa_mode", s.loop_prd_qa_mode), key_path="loop.prd_qa_mode", source=_source_for("loop", "prd_qa_mode")) or s.loop_prd_qa_mode
        s.loop_test_report = _to_str(loop.get("test_report", s.loop_test_report), key_path="loop.test_report", source=_source_for("loop", "test_report"))
        s.loop_review_report = _to_str(loop.get("review_report", s.loop_review_report), key_path="loop.review_report", source=_source_for("loop", "review_report"))
        s.loop_final_report = _to_str(loop.get("final_report", s.loop_final_report), key_path="loop.final_report", source=_source_for("loop", "final_report"))
        s.loop_auto_mode = _to_str(loop.get("auto_mode", s.loop_auto_mode), key_path="loop.auto_mode", source=_source_for("loop", "auto_mode")) or ""
        s.loop_max_feature_iters = _to_int(loop.get("max_feature_iters", s.loop_max_feature_iters), key_path="loop.max_feature_iters", source=_source_for("loop", "max_feature_iters"))
        s.loop_retry_failed = _to_bool(loop.get("retry_failed", s.loop_retry_failed), key_path="loop.retry_failed", source=_source_for("loop", "retry_failed"))
        s.loop_smoke_check = _to_bool(loop.get("smoke_check", s.loop_smoke_check), key_path="loop.smoke_check", source=_source_for("loop", "smoke_check"))
        s.loop_smoke_timeout = _to_int(loop.get("smoke_timeout", s.loop_smoke_timeout), key_path="loop.smoke_timeout", source=_source_for("loop", "smoke_timeout"))
        s.loop_max_tool_errors = _to_int(loop.get("max_tool_errors", s.loop_max_tool_errors), key_path="loop.max_tool_errors", source=_source_for("loop", "max_tool_errors"))

        mem = _ensure_table(merged, "memory", source=_source_for("memory"))
        s.memory_k = _to_int(mem.get("k", s.memory_k), key_path="memory.k", source=_source_for("memory", "k"))
        s.memory_inject_max_chars = _to_int(mem.get("inject_max_chars", s.memory_inject_max_chars), key_path="memory.inject_max_chars", source=_source_for("memory", "inject_max_chars"))
        s.memory_chunk_chars = _to_int(mem.get("chunk_chars", s.memory_chunk_chars), key_path="memory.chunk_chars", source=_source_for("memory", "chunk_chars"))
        s.memory_chunk_overlap = _to_int(mem.get("chunk_overlap", s.memory_chunk_overlap), key_path="memory.chunk_overlap", source=_source_for("memory", "chunk_overlap"))
        s.memory_vacuum_warn_mb = _to_float(mem.get("vacuum_warn_mb", s.memory_vacuum_warn_mb), key_path="memory.vacuum_warn_mb", source=_source_for("memory", "vacuum_warn_mb"))
        s.memory_exclude_dirs = _to_str_list(mem.get("exclude_dirs", s.memory_exclude_dirs), key_path="memory.exclude_dirs", source=_source_for("memory", "exclude_dirs"))
        s.memory_include_exts = _to_str_list(mem.get("include_exts", s.memory_include_exts), key_path="memory.include_exts", source=_source_for("memory", "include_exts"))

        ui = _ensure_table(merged, "ui", source=_source_for("ui"))
        s.ui_dashboard = _to_bool(ui.get("dashboard", s.ui_dashboard), key_path="ui.dashboard", source=_source_for("ui", "dashboard"))

        log = _ensure_table(merged, "logging", source=_source_for("logging"))
        s.log_level = _to_str(log.get("level", s.log_level), key_path="logging.level", source=_source_for("logging", "level"))
        s.log_console = _to_bool(log.get("console", s.log_console), key_path="logging.console", source=_source_for("logging", "console"))
        s.log_file = _to_bool(log.get("file", s.log_file), key_path="logging.file", source=_source_for("logging", "file"))
        s.log_raw_debug = _to_bool(log.get("raw_debug", s.log_raw_debug), key_path="logging.raw_debug", source=_source_for("logging", "raw_debug"))

        sandbox = _ensure_table(merged, "sandbox", source=_source_for("sandbox"))
        s.sandbox_enabled = _to_bool(sandbox.get("enabled", s.sandbox_enabled), key_path="sandbox.enabled", source=_source_for("sandbox", "enabled"))
        s.sandbox_mode = _to_str(sandbox.get("mode", s.sandbox_mode), key_path="sandbox.mode", source=_source_for("sandbox", "mode")) or s.sandbox_mode
        s.sandbox_docker_image = _to_str(sandbox.get("docker_image", s.sandbox_docker_image), key_path="sandbox.docker_image", source=_source_for("sandbox", "docker_image")) or s.sandbox_docker_image
        s.sandbox_network = _to_str(sandbox.get("network", s.sandbox_network), key_path="sandbox.network", source=_source_for("sandbox", "network")) or s.sandbox_network
        s.sandbox_fail_closed = _to_bool(sandbox.get("fail_closed", s.sandbox_fail_closed), key_path="sandbox.fail_closed", source=_source_for("sandbox", "fail_closed"))
        s.sandbox_env_allowlist = _to_str_list(sandbox.get("env_allowlist", s.sandbox_env_allowlist), key_path="sandbox.env_allowlist", source=_source_for("sandbox", "env_allowlist"))

        browser = _ensure_table(merged, "browser", source=_source_for("browser"))
        s.browser_headless = _to_bool(browser.get("headless", s.browser_headless), key_path="browser.headless", source=_source_for("browser", "headless"))
        s.browser_viewport_width = _to_int(browser.get("viewport_width", s.browser_viewport_width), key_path="browser.viewport_width", source=_source_for("browser", "viewport_width"))
        s.browser_viewport_height = _to_int(browser.get("viewport_height", s.browser_viewport_height), key_path="browser.viewport_height", source=_source_for("browser", "viewport_height"))
        s.browser_default_timeout = _to_int(browser.get("default_timeout", s.browser_default_timeout), key_path="browser.default_timeout", source=_source_for("browser", "default_timeout"))
        s.browser_console_buffer_max = _to_int(browser.get("console_buffer_max", s.browser_console_buffer_max), key_path="browser.console_buffer_max", source=_source_for("browser", "console_buffer_max"))
        s.browser_network_buffer_max = _to_int(browser.get("network_buffer_max", s.browser_network_buffer_max), key_path="browser.network_buffer_max", source=_source_for("browser", "network_buffer_max"))

        prx = _ensure_table(merged, "proxy", source=_source_for("proxy"))
        s.proxy_enabled = _to_bool(prx.get("enabled", s.proxy_enabled), key_path="proxy.enabled", source=_source_for("proxy", "enabled"))
        s.proxy_listen_port = _to_int(prx.get("listen_port", s.proxy_listen_port), key_path="proxy.listen_port", source=_source_for("proxy", "listen_port"))
        s.proxy_target_host = _to_str(prx.get("target_host", s.proxy_target_host), key_path="proxy.target_host", source=_source_for("proxy", "target_host"))
        s.proxy_target_port = _to_int(prx.get("target_port", s.proxy_target_port), key_path="proxy.target_port", source=_source_for("proxy", "target_port"))
        s.proxy_target_model = _to_str(prx.get("target_model", s.proxy_target_model), key_path="proxy.target_model", source=_source_for("proxy", "target_model"))
        s.proxy_provider_name = _to_str(prx.get("provider_name", s.proxy_provider_name), key_path="proxy.provider_name", source=_source_for("proxy", "provider_name"))
        s.proxy_provider_display = _to_str(prx.get("provider_display", s.proxy_provider_display), key_path="proxy.provider_display", source=_source_for("proxy", "provider_display"))
        s.proxy_model_id = _to_str(prx.get("model_id", s.proxy_model_id), key_path="proxy.model_id", source=_source_for("proxy", "model_id"))
        s.proxy_model_display = _to_str(prx.get("model_display", s.proxy_model_display), key_path="proxy.model_display", source=_source_for("proxy", "model_display"))
        s.proxy_api_key = _to_str(prx.get("api_key", s.proxy_api_key), key_path="proxy.api_key", source=_source_for("proxy", "api_key"))
        s.proxy_auto_start = _to_bool(prx.get("auto_start", s.proxy_auto_start), key_path="proxy.auto_start", source=_source_for("proxy", "auto_start"))
        s.proxy_log_requests = _to_bool(prx.get("log_requests", s.proxy_log_requests), key_path="proxy.log_requests", source=_source_for("proxy", "log_requests"))
        s.proxy_cors_enabled = _to_bool(prx.get("cors_enabled", s.proxy_cors_enabled), key_path="proxy.cors_enabled", source=_source_for("proxy", "cors_enabled"))
        s.proxy_cors_allow_origin = _to_str(prx.get("cors_allow_origin", s.proxy_cors_allow_origin), key_path="proxy.cors_allow_origin", source=_source_for("proxy", "cors_allow_origin"))

        agent = _ensure_table(merged, "agent", source=_source_for("agent"))
        s.agent_native = _to_bool(agent.get("native", s.agent_native), key_path="agent.native", source=_source_for("agent", "native"))
        s.agent_max_turns = _to_int(agent.get("max_turns", s.agent_max_turns), key_path="agent.max_turns", source=_source_for("agent", "max_turns"))
        s.agent_timeout = _to_int(agent.get("timeout", s.agent_timeout), key_path="agent.timeout", source=_source_for("agent", "timeout"))
        s.agent_max_output = _to_int(agent.get("max_output", s.agent_max_output), key_path="agent.max_output", source=_source_for("agent", "max_output"))

        agents = _ensure_table(merged, "agents", source=_source_for("agents"))
        s.agents_enabled = _to_bool(agents.get("enabled", s.agents_enabled), key_path="agents.enabled", source=_source_for("agents", "enabled"))
        s.agents_default_provider = _to_str(agents.get("default_provider", s.agents_default_provider), key_path="agents.default_provider", source=_source_for("agents", "default_provider")) or ""
        s.agents_default_model = _to_str(agents.get("default_model", s.agents_default_model), key_path="agents.default_model", source=_source_for("agents", "default_model")) or ""
        # Per-agent config
        code_cfg = _ensure_table(agents, "code", source=_source_for("agents", "code"))
        s.agent_code_model = _to_str(code_cfg.get("model", s.agent_code_model), key_path="agents.code.model", source=_source_for("agents", "code", "model")) or ""
        s.agent_code_permissions = _normalize_agent_permissions(_to_str_list(code_cfg.get("permissions", s.agent_code_permissions), key_path="agents.code.permissions", source=_source_for("agents", "code", "permissions")))
        plan_cfg = _ensure_table(agents, "plan", source=_source_for("agents", "plan"))
        s.agent_plan_model = _to_str(plan_cfg.get("model", s.agent_plan_model), key_path="agents.plan.model", source=_source_for("agents", "plan", "model")) or ""
        s.agent_plan_permissions = _normalize_agent_permissions(_to_str_list(plan_cfg.get("permissions", s.agent_plan_permissions), key_path="agents.plan.permissions", source=_source_for("agents", "plan", "permissions")))
        test_cfg = _ensure_table(agents, "test", source=_source_for("agents", "test"))
        s.agent_test_model = _to_str(test_cfg.get("model", s.agent_test_model), key_path="agents.test.model", source=_source_for("agents", "test", "model")) or ""
        s.agent_test_permissions = _normalize_agent_permissions(_to_str_list(test_cfg.get("permissions", s.agent_test_permissions), key_path="agents.test.permissions", source=_source_for("agents", "test", "permissions")))
        review_cfg = _ensure_table(agents, "review", source=_source_for("agents", "review"))
        s.agent_review_model = _to_str(review_cfg.get("model", s.agent_review_model), key_path="agents.review.model", source=_source_for("agents", "review", "model")) or ""
        s.agent_review_permissions = _normalize_agent_permissions(_to_str_list(review_cfg.get("permissions", s.agent_review_permissions), key_path="agents.review.permissions", source=_source_for("agents", "review", "permissions")))
        return s

    def as_dict(self) -> dict:
        return {
            "ollama": {"host": self.ollama_host, "embed_model": self.embed_model},
            "init": {
                "install_tools": self.init_install_tools,
                "node_tooling": self.init_node_tooling,
                "create_venv": self.init_create_venv,
                "playwright": self.init_playwright,
                "playwright_browsers": self.init_playwright_browsers,
                "playwright_cli": self.init_playwright_cli,
            },
            "loop": {
                "max_iters": self.loop_max_iters,
                "rollback_on_gate_fail": self.loop_rollback_on_gate_fail,
                "max_gate_fails": self.loop_max_gate_fails,
                "prd_refresh_every": self.loop_prd_refresh_every,
                "prd_refresh_mode": self.loop_prd_refresh_mode,
                "prd_qa_mode": self.loop_prd_qa_mode,
                "test_report": self.loop_test_report,
                "review_report": self.loop_review_report,
                "final_report": self.loop_final_report,
                "auto_mode": self.loop_auto_mode,
                "max_feature_iters": self.loop_max_feature_iters,
                "retry_failed": self.loop_retry_failed,
                "smoke_check": self.loop_smoke_check,
                "smoke_timeout": self.loop_smoke_timeout,
                "max_tool_errors": self.loop_max_tool_errors,
            },
            "memory": {
                "k": self.memory_k,
                "inject_max_chars": self.memory_inject_max_chars,
                "chunk_chars": self.memory_chunk_chars,
                "chunk_overlap": self.memory_chunk_overlap,
                "vacuum_warn_mb": self.memory_vacuum_warn_mb,
                "exclude_dirs": self.memory_exclude_dirs,
                "include_exts": self.memory_include_exts,
            },
            "ui": {"dashboard": self.ui_dashboard},
            "logging": {
                "level": self.log_level,
                "console": self.log_console,
                "file": self.log_file,
                "raw_debug": self.log_raw_debug,
            },
            "sandbox": {
                "enabled": self.sandbox_enabled,
                "mode": self.sandbox_mode,
                "docker_image": self.sandbox_docker_image,
                "network": self.sandbox_network,
                "fail_closed": self.sandbox_fail_closed,
                "env_allowlist": self.sandbox_env_allowlist,
            },
            "browser": {
                "headless": self.browser_headless,
                "viewport_width": self.browser_viewport_width,
                "viewport_height": self.browser_viewport_height,
                "default_timeout": self.browser_default_timeout,
                "console_buffer_max": self.browser_console_buffer_max,
                "network_buffer_max": self.browser_network_buffer_max,
            },
            "proxy": {
                "enabled": self.proxy_enabled,
                "listen_port": self.proxy_listen_port,
                "target_host": self.proxy_target_host,
                "target_port": self.proxy_target_port,
                "target_model": self.proxy_target_model,
                "provider_name": self.proxy_provider_name,
                "provider_display": self.proxy_provider_display,
                "model_id": self.proxy_model_id,
                "model_display": self.proxy_model_display,
                "api_key": self.proxy_api_key,
                "auto_start": self.proxy_auto_start,
                "log_requests": self.proxy_log_requests,
                "cors_enabled": self.proxy_cors_enabled,
                "cors_allow_origin": self.proxy_cors_allow_origin,
            },
            "agent": {
                "native": self.agent_native,
                "max_turns": self.agent_max_turns,
                "timeout": self.agent_timeout,
                "max_output": self.agent_max_output,
            },
            "agents": {
                "enabled": self.agents_enabled,
                "default_provider": self.agents_default_provider,
                "default_model": self.agents_default_model,
                "code": {"model": self.agent_code_model, "permissions": self.agent_code_permissions},
                "plan": {"model": self.agent_plan_model, "permissions": self.agent_plan_permissions},
                "test": {"model": self.agent_test_model, "permissions": self.agent_test_permissions},
                "review": {"model": self.agent_review_model, "permissions": self.agent_review_permissions},
            },
        }


def get_provider_config(settings: OpenRalphSettings, role: str = "") -> dict[str, object]:
    model_map = {
        "code": settings.agent_code_model,
        "plan": settings.agent_plan_model,
        "test": settings.agent_test_model,
        "review": settings.agent_review_model,
    }
    model = model_map.get(role, "") or settings.agents_default_model or settings.proxy_model_id
    return {
        "base_url": f"http://127.0.0.1:{settings.proxy_listen_port}",
        "api_key": settings.proxy_api_key,
        "model": model,
        "timeout": settings.agent_timeout,
    }


STARTER_TOML = """[ollama]
host = "http://localhost:11434"
embed_model = "nomic-embed-text"

[init]
install_tools = true
node_tooling = "local"
create_venv = false
playwright = true
playwright_browsers = true
playwright_cli = true             # Install @playwright/cli for agent browser commands

[loop]
max_iters = 10
rollback_on_gate_fail = false
max_gate_fails = 5
prd_refresh_every = 0
prd_refresh_mode = ""      # "" or "ask"
prd_qa_mode = "handoff"    # interactive|handoff|auto|auto-then-handoff
test_report = ".ralph/TEST_REPORT.md"
review_report = ".ralph/REVIEW_REPORT.md"
final_report = ".ralph/FINAL.md"
auto_mode = ""                         # "" (off) or "full" (PRD + plan + build all features)
max_feature_iters = 8                  # Max iterations per feature when auto_mode = "full"
retry_failed = true                    # Retry failed features on re-run
smoke_check = true                     # Run runtime smoke checks after gate PASS
smoke_timeout = 10                     # Per-check subprocess timeout in seconds
max_tool_errors = 0                    # Downgrade success to warnings if tool errors exceed this

[memory]
k = 8
inject_max_chars = 6000
chunk_chars = 1800
chunk_overlap = 200
vacuum_warn_mb = 200
exclude_dirs = [".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph"]
include_exts = [".md", ".mdx", ".markdown", ".txt", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css", ".scss", ".less", ".json", ".jsonc", ".yaml", ".yml", ".toml"]

[ui]
dashboard = true                        # Show live dashboard during 'openralph run'

[logging]
level = "INFO"                          # DEBUG, INFO, WARNING, ERROR, CRITICAL
console = false                         # Log to stderr (in addition to Rich output)
file = true                             # Log to .ralph/logs/openralph_*.log
raw_debug = true                        # Write full untruncated provider/tool payload logs

[sandbox]
enabled = true                          # Enable sandbox for bash tool execution
mode = "docker"                         # docker|local
docker_image = "python:3.12-slim"      # Image used for sandboxed bash commands
network = "bridge"                      # bridge|none
fail_closed = true                      # If docker is unavailable, fail instead of local fallback
env_allowlist = ["OLLAMA_HOST", "EMBED_MODEL", "BRAVE_API_KEY"]  # Env vars passed into container

[browser]
headless = true                         # Browser tools run with headless Chromium
viewport_width = 1280
viewport_height = 720
default_timeout = 10000                 # milliseconds
console_buffer_max = 500
network_buffer_max = 200

[proxy]
enabled = true                          # Enable LLM proxy server
listen_port = 18889                     # Local port proxy listens on
target_host = "127.0.0.1"               # Backend LLM host
target_port = 30000                     # Backend LLM port
target_model = "openai/gpt-oss-120b"    # Model name to send to backend
provider_name = "openclaw"              # Provider ID
provider_display = "DGX gpt-OSS"        # Provider display name
model_id = "chatgpt-oss"                # Model ID
model_display = "ChatGPT-OSS 120B"      # Model display name
api_key = "LOCAL_DGX"                   # API key to use
auto_start = true                       # Auto-start proxy on init/run
log_requests = false                    # Log each proxied request
cors_enabled = false                    # Handle CORS preflight locally
cors_allow_origin = "*"                 # Access-Control-Allow-Origin when CORS is enabled

[agent]
native = true                           # Use native agent (OpenCode removed)
max_turns = 80                          # Max tool call iterations per agent run
timeout = 120                           # Per-tool timeout in seconds
max_output = 50000                      # Max chars per tool output

[agents]
enabled = true                          # Enable multi-agent support
default_provider = ""                   # Default provider for all agents (empty = use proxy provider)
default_model = ""                      # Default model for all agents (empty = use proxy model)

[agents.code]
model = ""                              # Model override for code agent (empty = use default)
permissions = ["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search", "search", "browser_navigate", "browser_click", "browser_fill", "browser_screenshot", "browser_snapshot", "browser_evaluate", "browser_console", "browser_network"]

[agents.plan]
model = ""                              # Model override for plan agent (empty = use default)
permissions = ["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search"]

[agents.test]
model = ""                              # Model override for test agent (empty = use default)
permissions = ["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search", "browser_navigate", "browser_click", "browser_fill", "browser_screenshot", "browser_snapshot", "browser_evaluate", "browser_console", "browser_network"]

[agents.review]
model = ""                              # Model override for review agent (empty = use default)
permissions = ["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "repo_search"]
"""
