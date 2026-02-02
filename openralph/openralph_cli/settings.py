from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import sys

try:
    import tomllib  # py>=3.11
except Exception:
    import tomli as tomllib  # type: ignore

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
    with path.open("rb") as f:
        return tomllib.load(f)

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

    # OpenCode bundling
    opencode_auto_install: bool = True
    opencode_version: str = ""  # empty = latest

    # Init
    init_with_opencode_json: bool = True
    init_force_opencode_json: bool = False
    init_write_skills: bool = True
    init_force_skills: bool = False
    init_install_tools: bool = True
    init_node_tooling: str = "global"  # global|local
    init_create_venv: bool = False
    init_playwright: bool = True
    init_playwright_browsers: bool = True

    # Loop
    loop_max_iters: int = 10
    loop_rollback_on_gate_fail: bool = False
    loop_max_gate_fails: int = 3

    # Memory
    memory_k: int = 8
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
    agent_code_permissions: list[str] = field(default_factory=lambda: ["bash", "edit", "skill", "lsp", "question"])
    agent_plan_permissions: list[str] = field(default_factory=lambda: ["skill", "question"])
    agent_test_permissions: list[str] = field(default_factory=lambda: ["bash", "skill", "lsp", "question"])
    agent_review_permissions: list[str] = field(default_factory=lambda: ["skill", "question"])

    @staticmethod
    def load(repo: Path) -> "OpenRalphSettings":
        repo = repo.resolve()
        s = OpenRalphSettings()
        g = _load_toml(global_config_path())
        r = _load_toml(repo_config_path(repo))
        merged = _deep_merge(g, r)

        if os.environ.get("OLLAMA_HOST"):
            merged.setdefault("ollama", {})
            merged["ollama"]["host"] = os.environ["OLLAMA_HOST"]
        if os.environ.get("EMBED_MODEL"):
            merged.setdefault("ollama", {})
            merged["ollama"]["embed_model"] = os.environ["EMBED_MODEL"]

        oll = merged.get("ollama", {})
        s.ollama_host = oll.get("host", s.ollama_host)
        s.embed_model = oll.get("embed_model", s.embed_model)

        oc = merged.get("opencode", {})
        s.opencode_auto_install = oc.get("auto_install", s.opencode_auto_install)
        s.opencode_version = oc.get("version", s.opencode_version) or ""

        ini = merged.get("init", {})
        s.init_with_opencode_json = ini.get("with_opencode_json", s.init_with_opencode_json)
        s.init_force_opencode_json = ini.get("force_opencode_json", s.init_force_opencode_json)
        s.init_write_skills = ini.get("write_skills", s.init_write_skills)
        s.init_force_skills = ini.get("force_skills", s.init_force_skills)
        s.init_install_tools = ini.get("install_tools", s.init_install_tools)
        s.init_node_tooling = ini.get("node_tooling", s.init_node_tooling)
        s.init_create_venv = ini.get("create_venv", s.init_create_venv)
        s.init_playwright = ini.get("playwright", s.init_playwright)
        s.init_playwright_browsers = ini.get("playwright_browsers", s.init_playwright_browsers)

        loop = merged.get("loop", {})
        s.loop_max_iters = loop.get("max_iters", s.loop_max_iters)
        s.loop_rollback_on_gate_fail = loop.get("rollback_on_gate_fail", s.loop_rollback_on_gate_fail)
        s.loop_max_gate_fails = loop.get("max_gate_fails", s.loop_max_gate_fails)

        mem = merged.get("memory", {})
        s.memory_k = mem.get("k", s.memory_k)
        s.memory_chunk_chars = mem.get("chunk_chars", s.memory_chunk_chars)
        s.memory_chunk_overlap = mem.get("chunk_overlap", s.memory_chunk_overlap)
        s.memory_vacuum_warn_mb = float(mem.get("vacuum_warn_mb", s.memory_vacuum_warn_mb))
        s.memory_exclude_dirs = mem.get("exclude_dirs", s.memory_exclude_dirs)
        s.memory_include_exts = mem.get("include_exts", s.memory_include_exts)

        log = merged.get("logging", {})
        s.log_level = log.get("level", s.log_level)
        s.log_console = log.get("console", s.log_console)
        s.log_file = log.get("file", s.log_file)

        prx = merged.get("proxy", {})
        s.proxy_enabled = prx.get("enabled", s.proxy_enabled)
        s.proxy_listen_port = int(prx.get("listen_port", s.proxy_listen_port))
        s.proxy_target_host = prx.get("target_host", s.proxy_target_host)
        s.proxy_target_port = int(prx.get("target_port", s.proxy_target_port))
        s.proxy_target_model = prx.get("target_model", s.proxy_target_model)
        s.proxy_provider_name = prx.get("provider_name", s.proxy_provider_name)
        s.proxy_provider_display = prx.get("provider_display", s.proxy_provider_display)
        s.proxy_model_id = prx.get("model_id", s.proxy_model_id)
        s.proxy_model_display = prx.get("model_display", s.proxy_model_display)
        s.proxy_api_key = prx.get("api_key", s.proxy_api_key)
        s.proxy_auto_start = prx.get("auto_start", s.proxy_auto_start)

        agents = merged.get("agents", {})
        s.agents_enabled = agents.get("enabled", s.agents_enabled)
        s.agents_default_provider = agents.get("default_provider", s.agents_default_provider) or ""
        s.agents_default_model = agents.get("default_model", s.agents_default_model) or ""
        # Per-agent config
        code_cfg = agents.get("code", {})
        s.agent_code_model = code_cfg.get("model", s.agent_code_model) or ""
        s.agent_code_permissions = code_cfg.get("permissions", s.agent_code_permissions)
        plan_cfg = agents.get("plan", {})
        s.agent_plan_model = plan_cfg.get("model", s.agent_plan_model) or ""
        s.agent_plan_permissions = plan_cfg.get("permissions", s.agent_plan_permissions)
        test_cfg = agents.get("test", {})
        s.agent_test_model = test_cfg.get("model", s.agent_test_model) or ""
        s.agent_test_permissions = test_cfg.get("permissions", s.agent_test_permissions)
        review_cfg = agents.get("review", {})
        s.agent_review_model = review_cfg.get("model", s.agent_review_model) or ""
        s.agent_review_permissions = review_cfg.get("permissions", s.agent_review_permissions)
        return s

    def as_dict(self) -> dict:
        return {
            "ollama": {"host": self.ollama_host, "embed_model": self.embed_model},
            "opencode": {"auto_install": self.opencode_auto_install, "version": self.opencode_version},
            "init": {
                "with_opencode_json": self.init_with_opencode_json,
                "force_opencode_json": self.init_force_opencode_json,
                "write_skills": self.init_write_skills,
                "force_skills": self.init_force_skills,
                "install_tools": self.init_install_tools,
                "node_tooling": self.init_node_tooling,
                "create_venv": self.init_create_venv,
                "playwright": self.init_playwright,
                "playwright_browsers": self.init_playwright_browsers,
            },
            "loop": {
                "max_iters": self.loop_max_iters,
                "rollback_on_gate_fail": self.loop_rollback_on_gate_fail,
                "max_gate_fails": self.loop_max_gate_fails,
            },
            "memory": {
                "k": self.memory_k,
                "chunk_chars": self.memory_chunk_chars,
                "chunk_overlap": self.memory_chunk_overlap,
                "vacuum_warn_mb": self.memory_vacuum_warn_mb,
                "exclude_dirs": self.memory_exclude_dirs,
                "include_exts": self.memory_include_exts,
            },
            "logging": {
                "level": self.log_level,
                "console": self.log_console,
                "file": self.log_file,
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

STARTER_TOML = """[ollama]
host = "http://localhost:11434"
embed_model = "nomic-embed-text"

[opencode]
auto_install = true
version = ""            # empty = latest

[init]
with_opencode_json = true
force_opencode_json = false
write_skills = true
force_skills = false
install_tools = true
node_tooling = "local"
create_venv = false
playwright = true
playwright_browsers = true

[loop]
max_iters = 10
rollback_on_gate_fail = false
max_gate_fails = 3

[memory]
k = 8
chunk_chars = 1800
chunk_overlap = 200
vacuum_warn_mb = 200
exclude_dirs = [".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph"]
include_exts = [".md", ".mdx", ".markdown", ".txt", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css", ".scss", ".less", ".json", ".jsonc", ".yaml", ".yml", ".toml"]

[logging]
level = "INFO"                          # DEBUG, INFO, WARNING, ERROR, CRITICAL
console = false                         # Log to stderr (in addition to Rich output)
file = true                             # Log to .ralph/logs/openralph_*.log

[proxy]
enabled = false                         # Enable OpenCode proxy server
listen_port = 18889                     # Local port proxy listens on
target_host = "127.0.0.1"               # Backend LLM host
target_port = 30000                     # Backend LLM port
target_model = "openai/gpt-oss-120b"    # Model name to send to backend
provider_name = "openclaw"              # Provider ID in opencode.json
provider_display = "DGX gpt-OSS"        # Provider display name
model_id = "chatgpt-oss"                # Model ID in opencode.json
model_display = "ChatGPT-OSS 120B"      # Model display name
api_key = "LOCAL_DGX"                   # API key to use
auto_start = true                       # Auto-start proxy on init/run

[agents]
enabled = true                          # Enable multi-agent support in opencode.json
default_provider = ""                   # Default provider for all agents (empty = use proxy provider)
default_model = ""                      # Default model for all agents (empty = use proxy model)

[agents.code]
model = ""                              # Model override for code agent (empty = use default)
permissions = ["bash", "edit", "skill", "lsp", "question"]

[agents.plan]
model = ""                              # Model override for plan agent (empty = use default)
permissions = ["skill", "question"]     # Plan agent: read-only, no edit/bash

[agents.test]
model = ""                              # Model override for test agent (empty = use default)
permissions = ["bash", "skill", "lsp", "question"]  # Test agent: can run tests, no edit

[agents.review]
model = ""                              # Model override for review agent (empty = use default)
permissions = ["skill", "question"]     # Review agent: read-only analysis
"""
