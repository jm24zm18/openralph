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
"""
