from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json
import os

@dataclass(frozen=True)
class ProxyProviderOptions:
    enabled: bool = False
    listen_port: int = 18889
    provider_name: str = "openclaw"
    provider_display: str = "DGX gpt-OSS"
    model_id: str = "chatgpt-oss"
    model_display: str = "ChatGPT-OSS 120B"
    api_key: str = "LOCAL_DGX"

@dataclass(frozen=True)
class AgentConfig:
    name: str
    model: str = ""  # empty = use default
    permissions: tuple[str, ...] = ("bash", "edit", "skill", "lsp", "question", "repo_browser", "external_directory", "web_search", "grep")

@dataclass(frozen=True)
class AgentsOptions:
    enabled: bool = True
    default_provider: str = ""  # empty = use proxy provider
    default_model: str = ""  # empty = use proxy model
    code: AgentConfig = field(default_factory=lambda: AgentConfig(name="code"))
    plan: AgentConfig = field(default_factory=lambda: AgentConfig(
        name="plan", permissions=("skill", "question", "repo_browser", "external_directory")))
    test: AgentConfig = field(default_factory=lambda: AgentConfig(
        name="test", permissions=("bash", "skill", "lsp", "question", "repo_browser", "external_directory")))
    review: AgentConfig = field(default_factory=lambda: AgentConfig(
        name="review", permissions=("skill", "question", "repo_browser", "external_directory")))

@dataclass(frozen=True)
class OpenCodeConfigOptions:
    node_tooling: str = "global"  # global|local
    prefer_venvs: bool = True
    proxy: ProxyProviderOptions = field(default_factory=ProxyProviderOptions)
    agents: AgentsOptions = field(default_factory=AgentsOptions)

def _path_with_preference(opts: OpenCodeConfigOptions) -> str:
    parts = []
    if opts.prefer_venvs:
        if os.name == "nt":
            parts += ["${workspaceFolder}/.venv/Scripts", "${workspaceFolder}/venv/Scripts"]
        else:
            parts += ["${workspaceFolder}/.venv/bin", "${workspaceFolder}/venv/bin"]
    if opts.node_tooling == "local":
        parts += ["${workspaceFolder}/.ralph/node-tools/node_modules/.bin"]
    parts += ["${env:PATH}"]
    sep = ";" if os.name == "nt" else ":"
    return sep.join(parts)

def build_opencode_json(opts: OpenCodeConfigOptions) -> dict:
    lsp_env = {"PATH": _path_with_preference(opts)}
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "bash": "allow",
            "edit": "allow",
            "skill": "allow",
            "lsp": "allow",
            "question": "allow",
            "repo_browser": "allow",
            "external_directory": "allow",
            "web_search": "allow",
            "grep": "allow",
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

    if opts.proxy.enabled:
        proxy_api = f"http://localhost:{opts.proxy.listen_port}/v1"
        config["provider"] = {
            opts.proxy.provider_name: {
                "api": proxy_api,
                "name": opts.proxy.provider_display,
                "id": opts.proxy.provider_name,
                "npm": "@ai-sdk/openai-compatible",
                "models": {
                    f"{opts.proxy.model_id}:120b": {
                        "id": opts.proxy.model_id,
                        "name": opts.proxy.model_display,
                    }
                },
                "options": {
                    "apiKey": opts.proxy.api_key,
                    "baseURL": proxy_api,
                },
            }
        }

    if opts.agents.enabled:
        config["agent"] = _build_agents_block(opts)

    return config


def _build_agents_block(opts: OpenCodeConfigOptions) -> dict:
    default_provider = opts.agents.default_provider or (opts.proxy.provider_name if opts.proxy.enabled else "")
    default_model = opts.agents.default_model or (opts.proxy.model_id if opts.proxy.enabled else "")

    def build_agent(agent_cfg: AgentConfig) -> dict:
        agent_model = agent_cfg.model or default_model
        agent_block: dict = {
            "permission": {perm: "allow" for perm in agent_cfg.permissions}
        }
        # Set model if we have one (provider:model format or just model)
        if agent_model:
            if default_provider and ":" not in agent_model:
                agent_block["model"] = f"{default_provider}/{agent_model}"
            else:
                agent_block["model"] = agent_model
        return agent_block

    return {
        "code": build_agent(opts.agents.code),
        "plan": build_agent(opts.agents.plan),
        "test": build_agent(opts.agents.test),
        "review": build_agent(opts.agents.review),
    }

def write_opencode_json(repo: Path, *, force: bool, opts: OpenCodeConfigOptions) -> Path:
    repo = repo.resolve()
    path = repo / "opencode.json"
    if path.exists() and not force:
        return path
    path.write_text(json.dumps(build_opencode_json(opts), indent=2) + "\n", encoding="utf-8")
    return path
