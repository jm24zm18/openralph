from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass(frozen=True)
class OpenCodeConfigOptions:
    node_tooling: str = "global"  # global|local
    prefer_venvs: bool = True

def _path_with_preference(opts: OpenCodeConfigOptions) -> str:
    parts = []
    if opts.prefer_venvs:
        parts += ["${workspaceFolder}/.venv/bin", "${workspaceFolder}/venv/bin"]
    if opts.node_tooling == "local":
        parts += ["${workspaceFolder}/.ralph/node-tools/node_modules/.bin"]
    parts += ["${env:PATH}"]
    return ":".join(parts)

def build_opencode_json(opts: OpenCodeConfigOptions) -> dict:
    lsp_env = {"PATH": _path_with_preference(opts)}
    return {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "bash": "allow",
            "edit": "allow",
            "skill": "allow",
            "lsp": "allow",
            "question": "allow",
        },
        "lsp": {
            "pylsp": {"command": ["pylsp"], "extensions": [".py", ".pyi"], "env": lsp_env},
            "tsserver-local": {
                "command": ["typescript-language-server", "--stdio"],
                "extensions": [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"],
                "env": lsp_env,
                "initialization": {"preferences": {"importModuleSpecifierPreference": "relative"}},
            },
            "html-local": {"command": ["vscode-html-language-server", "--stdio"], "extensions": [".html", ".htm"], "env": lsp_env},
            "css-local": {"command": ["vscode-css-language-server", "--stdio"], "extensions": [".css", ".scss", ".less"], "env": lsp_env},
        },
    }

def write_opencode_json(repo: Path, *, force: bool, opts: OpenCodeConfigOptions) -> Path:
    repo = repo.resolve()
    path = repo / "opencode.json"
    if path.exists() and not force:
        return path
    path.write_text(json.dumps(build_opencode_json(opts), indent=2) + "\n", encoding="utf-8")
    return path
