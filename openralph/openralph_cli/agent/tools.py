from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
import subprocess
import difflib
import fnmatch
import re
import logging
import shlex
import urllib.error
import os

log = logging.getLogger(__name__)


TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command. Use for running tests, builds, git operations, installing dependencies, etc. Commands run in the repository root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 120, max 600)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content with line numbers. Use start_line/end_line for large files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to repo root)"},
                "start_line": {"type": "integer", "description": "Start line number (1-indexed, inclusive)"},
                "end_line": {"type": "integer", "description": "End line number (1-indexed, inclusive)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates the file if it doesn't exist, or overwrites if it does. Creates parent directories as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to repo root)"},
                "content": {"type": "string", "description": "The content to write to the file"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Apply a targeted edit to a file using exact string matching. The old_text must match exactly (including whitespace/indentation). For multiple edits to the same file, call this tool multiple times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to repo root)"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace it with"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "glob",
        "description": "Find files matching a glob pattern. Returns paths relative to repo root. Useful for discovering project structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts', '*.json')"},
                "path": {"type": "string", "description": "Base directory to search from (default: repo root)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Search for a regex pattern in files. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "File or directory to search in (default: repo root)"},
                "include": {"type": "string", "description": "Glob pattern to filter files (e.g., '*.py', '*.ts')"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the contents of a directory. Shows files and subdirectories with type indicators. Use this to explore the project structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (relative to repo root, default: repo root)"},
            },
            "required": [],
        },
    },
    {
        "name": "search",
        "description": "Search the web for best practices or documentation. Uses Brave Search or DuckDuckGo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results to return (default 5, max 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "repo_search",
        "description": "Search the repository for a text query (regex-escaped literal match).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text query to search for in repository files"},
                "path": {"type": "string", "description": "Base directory for repo search (default: repo root)"},
                "max_results": {"type": "integer", "description": "Max matches to return (default 20, max 200)"},
            },
            "required": ["query"],
        },
    },
]

_TOOL_NAMES = {t["name"] for t in TOOLS}
_TOOL_SUFFIX_TOKENS = ("commentary", "analysis", "assistant", "final", "json", "code")


@dataclass
class ToolContext:
    repo: Path
    timeout_default: int = 120
    timeout_max: int = 600
    max_output_chars: int = 50000
    max_file_lines: int = 2000
    allowed_tools: set[str] | None = None
    sandbox_enabled: bool = True
    sandbox_mode: str = "docker"  # docker|local
    sandbox_docker_image: str = "python:3.12-slim"
    sandbox_network: str = "bridge"  # bridge|none
    sandbox_fail_closed: bool = True
    sandbox_env_allowlist: list[str] = field(default_factory=lambda: ["OLLAMA_HOST", "EMBED_MODEL", "BRAVE_API_KEY"])
    exclude_patterns: list[str] = field(default_factory=lambda: [
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        "dist", "build", ".ralph", ".mypy_cache", ".pytest_cache",
    ])


def execute_tool(name: str, args: dict, ctx: ToolContext) -> tuple[str, bool]:
    """
    Execute a tool and return (result, is_error).
    """
    try:
        if "_invalid_json" in args:
            raw = args.get("_invalid_json")
            reason = args.get("_invalid_reason") or "invalid JSON"
            recovered = _recover_args_from_invalid_json(name, raw)
            if recovered:
                log.debug("Recovered invalid JSON for %s: %s", name, recovered)
                args = recovered
            else:
                return (
                    "Error: tool arguments are invalid JSON. "
                    f"Reason: {reason}. "
                    f"Raw arguments: {raw!r}. "
                    "Provide a valid JSON object like {\"command\": \"python3 -m pytest -q\"}. "
                    "If content is large, use bash with a heredoc.",
                    True,
                )
        name, args = _normalize_tool_args(name, args)
        alias = _resolve_tool_alias(name, args)
        if alias:
            name, args = alias
        name, args = _normalize_tool_args(name, args)
        if ctx.allowed_tools is not None and name not in ctx.allowed_tools:
            allowed = ", ".join(sorted(ctx.allowed_tools))
            return f"Error: tool '{name}' is not permitted for this agent role. Allowed tools: {allowed}", True
        error = _validate_tool_args(name, args)
        if error:
            return error, True

        if name == "bash":
            return _run_bash(args["command"], args.get("timeout"), ctx)
        elif name == "read_file":
            return _read_file(args["path"], args.get("start_line"), args.get("end_line"), ctx), False
        elif name == "write_file":
            content = args["content"]
            if len(content) > 8000:
                return _write_file_via_bash(args["path"], content, ctx)
            return _write_file(args["path"], content, ctx), False
        elif name == "edit_file":
            return _edit_file(args["path"], args["old_text"], args["new_text"], ctx)
        elif name == "glob":
            return _glob(args["pattern"], args.get("path", "."), ctx), False
        elif name == "grep":
            return _grep(args["pattern"], args.get("path", "."), args.get("include"), ctx), False
        elif name == "list_dir":
            return _list_dir(args.get("path", "."), ctx), False
        elif name == "search":
            query = args.get("query") or args.get("pattern") or args.get("q", "")
            result = _search_web(query, args.get("max_results"), ctx)
            is_error = result.startswith("Error:")
            return result, is_error
        elif name == "repo_search":
            query = args.get("query") or args.get("pattern") or args.get("q", "")
            result = _search_repo(query, args.get("path"), args.get("max_results"), ctx)
            is_error = result.startswith("Error:")
            return result, is_error
        else:
            return _unknown_tool_error(name), True
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        return f"Error: {type(e).__name__}: {e}", True


def _normalize_tool_args(name: str, args: dict | None) -> tuple[str, dict]:
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        args = {"value": args}
    lowered = _canonical_tool_name(name)
    if lowered:
        name = lowered

    if lowered in {"open_file", "openfile"}:
        name = "read_file"

    if lowered in {"bash", "shell"}:
        args = _normalize_args(args, {
            "command": ["cmd", "command_line", "shell", "bash", "run"],
            "timeout": ["timeout_seconds", "seconds"],
        })
        if "command" not in args and "value" in args:
            args["command"] = str(args["value"])

    if lowered in {"read_file", "open_file", "openfile"}:
        args = _normalize_args(args, {
            "path": ["file", "filepath", "filename"],
            "start_line": ["line_start", "start", "from_line"],
            "end_line": ["line_end", "end", "to_line"],
        })
        if "path" not in args and "value" in args:
            args["path"] = str(args["value"])

    if lowered == "write_file":
        args = _normalize_args(args, {
            "path": ["file", "filepath", "filename"],
            "content": ["text", "contents", "body", "data"],
        })

    if lowered == "edit_file":
        args = _normalize_args(args, {
            "path": ["file", "filepath", "filename"],
            "old_text": ["old", "before", "find", "search"],
            "new_text": ["new", "after", "replace", "replacement"],
        })

    if lowered == "glob":
        args = _normalize_args(args, {
            "pattern": ["glob", "pathspec"],
            "path": ["base", "dir", "directory"],
        })

    if lowered == "grep":
        args = _normalize_args(args, {
            "pattern": ["regex", "query", "search"],
            "path": ["file", "filepath", "dir", "directory"],
            "include": ["glob", "filter"],
        })

    if lowered in {"list_dir", "ls"}:
        name = "list_dir"
        args = _normalize_args(args, {
            "path": ["dir", "directory"],
        })

    if lowered == "search":
        args = _normalize_args(args, {
            "query": ["q", "pattern", "search"],
            "max_results": ["limit", "max"],
        })
    if lowered in {"repo_search", "search_repo"}:
        name = "repo_search"
        args = _normalize_args(args, {
            "query": ["q", "pattern", "search"],
            "path": ["base", "dir", "directory"],
            "max_results": ["limit", "max"],
        })

    return name, args


def _normalize_args(args: dict, mapping: dict[str, list[str]]) -> dict:
    normalized = dict(args)
    for canonical, aliases in mapping.items():
        if canonical in normalized and normalized[canonical] not in (None, ""):
            continue
        for alias in aliases:
            if alias in normalized and normalized[alias] not in (None, ""):
                normalized[canonical] = normalized[alias]
                break
    return normalized


def _resolve_tool_alias(name: str, args: dict) -> tuple[str, dict] | None:
    lowered = _canonical_tool_name(name)
    if lowered == "bashjson":
        return "bash", args
    if lowered == "open_file":
        return "read_file", args
    if lowered == "mkdir":
        path = args.get("path") or args.get("dir") or args.get("directory")
        command = args.get("command")
        if isinstance(command, str) and command.strip():
            return "bash", {"command": command.strip()}
        if isinstance(path, list):
            path = " ".join(shlex.quote(str(p)) for p in path)
        if isinstance(path, str) and path.strip():
            return "bash", {"command": f"mkdir -p {shlex.quote(path.strip())}"}
    if lowered in {"delete_file", "remove_file", "rm_file"}:
        path = args.get("path") or args.get("file") or args.get("filepath")
        if isinstance(path, str) and path.strip():
            return "bash", {"command": f"rm -f {shlex.quote(path.strip())}"}
    if lowered == "search_repo":
        return "repo_search", args
    if lowered in {"print_tree", "ls_tree", "tree"}:
        return "list_dir", args
    if lowered in _TOOL_NAMES:
        return lowered, args
    return None


def _canonical_tool_name(name: str) -> str:
    lowered = (name or "").strip().lower()
    if not lowered:
        return ""
    if lowered in _TOOL_NAMES:
        return lowered

    # Drop common suffix leak tokens repeatedly (e.g., list_dirjsoncommentary).
    candidate = lowered
    changed = True
    while changed and candidate:
        changed = False
        for suffix in _TOOL_SUFFIX_TOKENS:
            if candidate.endswith(suffix) and len(candidate) > len(suffix):
                trimmed = candidate[: -len(suffix)].rstrip("_")
                if trimmed and trimmed != candidate:
                    candidate = trimmed
                    changed = True
                    break
    if candidate in _TOOL_NAMES:
        return candidate

    # Recover merged known tool names like "list_dirjson" (no separator).
    for tool_name in _TOOL_NAMES:
        if lowered.startswith(tool_name):
            tail = lowered[len(tool_name):]
            if not tail:
                return tool_name
            tail_candidate = tail
            tail_changed = True
            while tail_changed and tail_candidate:
                tail_changed = False
                for suffix in _TOOL_SUFFIX_TOKENS:
                    if tail_candidate.endswith(suffix) and len(tail_candidate) >= len(suffix):
                        tail_candidate = tail_candidate[: -len(suffix)]
                        tail_changed = True
                        break
            if tail_candidate == "":
                return tool_name

    return lowered


def _validate_tool_args(name: str, args: dict) -> str | None:
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if not tool:
        return None
    required = tool.get("input_schema", {}).get("required", [])
    missing = [k for k in required if k not in args]
    if missing:
        schema = tool.get("input_schema", {})
        examples = _tool_examples(name)
        provided = ", ".join(sorted(args.keys())) or "(none)"
        raw = args.get("_raw")
        raw_hint = f" Raw arguments: {raw!r}." if raw else ""
        return (
            f"Error: missing required arguments for tool '{name}': {', '.join(missing)}. "
            f"Provided keys: {provided}.{raw_hint} Schema: {schema}\n"
            f"{examples}"
        )
    return None


def _recover_args_from_invalid_json(name: str, raw: object) -> dict | None:
    if not isinstance(raw, str):
        return None

    targets: dict[str, list[str]] = {
        "bash": ["command"],
        "write_file": ["path", "content"],
        "edit_file": ["path", "old_text", "new_text"],
        "read_file": ["path", "start_line", "end_line"],
        "glob": ["pattern", "path"],
        "grep": ["pattern", "path", "include"],
        "list_dir": ["path"],
        "search": ["query", "max_results"],
        "repo_search": ["query", "path", "max_results"],
        "search_repo": ["query", "path", "max_results"],
    }
    keys = targets.get(name, [])
    if not keys:
        return None

    recovered: dict[str, str] = {}
    for key in keys:
        value = _extract_json_string_value(raw, key)
        if value is not None:
            recovered[key] = value

    if recovered:
        return recovered
    return None


def _extract_json_string_value(raw: str, key: str) -> str | None:
    token = f"\"{key}\""
    idx = raw.find(token)
    if idx == -1:
        return None
    i = raw.find(":", idx + len(token))
    if i == -1:
        return None
    i += 1
    while i < len(raw) and raw[i] in " \t\r\n":
        i += 1
    if i >= len(raw) or raw[i] != "\"":
        return None
    i += 1
    buf = []
    escaped = False
    while i < len(raw):
        ch = raw[i]
        if escaped:
            if ch == "n":
                buf.append("\n")
            elif ch == "t":
                buf.append("\t")
            elif ch == "r":
                buf.append("\r")
            else:
                buf.append(ch)
            escaped = False
        else:
            if ch == "\\":
                escaped = True
            elif ch == "\"":
                return "".join(buf)
            else:
                buf.append(ch)
        i += 1
    return None


def _write_file_via_bash(path: str, content: str, ctx: ToolContext) -> tuple[str, bool]:
    p = _resolve_path(path, ctx)
    delimiter = "OPENRALPH_EOF"
    if delimiter in content:
        delimiter = f"{delimiter}_{abs(hash(content))}"
    cmd = (
        f"mkdir -p {shlex.quote(str(p.parent))} && "
        f"cat <<'{delimiter}' > {shlex.quote(str(p))}\n{content}\n{delimiter}\n"
    )
    return _run_bash(cmd, None, ctx)


def _unknown_tool_error(name: str) -> str:
    available = ", ".join(t["name"] for t in TOOLS)
    hint = _tool_alias_hints(name)
    return (
        f"Unknown tool: {name}. Available tools: {available}.\n"
        f"{hint}"
        "If you need to run a shell command, use tool 'bash' with {\"command\": \"...\"}."
    )


def _tool_alias_hints(name: str) -> str:
    lowered = name.lower()
    hints = {
        "open_file": "Hint: use 'read_file' with {\"path\": \"...\"} and optional start_line/end_line.\n",
        "mkdir": "Hint: use 'bash' with {\"command\": \"mkdir -p <path>\"}.\n",
        "bashjson": "Hint: use 'bash' with {\"command\": \"...\"}.\n",
        "ls": "Hint: use 'list_dir' with optional {\"path\": \"...\"}.\n",
        "print_tree": "Hint: use 'list_dir' with optional {\"path\": \"...\"}.\n",
        "list_dircommentary": "Hint: use 'list_dir' with optional {\"path\": \"...\"}.\n",
    }
    return hints.get(lowered, "")


def _tool_examples(name: str) -> str:
    examples = {
        "bash": "Example: {\"command\": \"python3 -m pytest -q\", \"timeout\": 120}",
        "read_file": "Example: {\"path\": \"README.md\", \"start_line\": 1, \"end_line\": 200}",
        "write_file": "Example: {\"path\": \"notes.txt\", \"content\": \"Hello\"}",
        "edit_file": "Example: {\"path\": \"app.py\", \"old_text\": \"foo\", \"new_text\": \"bar\"}",
        "glob": "Example: {\"pattern\": \"**/*.py\", \"path\": \".\"}",
        "grep": "Example: {\"pattern\": \"TODO\", \"path\": \".\", \"include\": \"*.py\"}",
        "list_dir": "Example: {\"path\": \".\"}",
        "search": "Example: {\"query\": \"pytest fixtures\", \"max_results\": 5}",
        "repo_search": "Example: {\"query\": \"GameOverScreen\", \"path\": \".\", \"max_results\": 20}",
    }
    return examples.get(name, "")


def _resolve_path(path_str: str, ctx: ToolContext) -> Path:
    """Resolve a path relative to repo, with security checks."""
    p = Path(path_str)
    if p.is_absolute():
        p = p.resolve()
    else:
        p = (ctx.repo / p).resolve()

    # Security: ensure path is under repo
    repo_resolved = ctx.repo.resolve()
    try:
        p.relative_to(repo_resolved)
    except ValueError:
        raise ValueError(f"Path '{path_str}' resolves outside repository")

    return p


def _should_exclude(path: Path, ctx: ToolContext) -> bool:
    """Check if a path should be excluded based on patterns."""
    parts = path.parts
    for pattern in ctx.exclude_patterns:
        if pattern in parts:
            return True
    return False


def _run_bash(command: str, timeout: int | None, ctx: ToolContext) -> tuple[str, bool]:
    """Execute a bash command in the repository (sandboxed by default)."""
    if ctx.sandbox_enabled and ctx.sandbox_mode == "docker":
        return _run_bash_docker(command, timeout, ctx)
    return _run_bash_local(command, timeout, ctx)


def _run_bash_local(command: str, timeout: int | None, ctx: ToolContext) -> tuple[str, bool]:
    timeout = min(timeout or ctx.timeout_default, ctx.timeout_max)

    env = os.environ.copy()
    env = _augment_path_for_runtime(env, ctx.repo)

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=str(ctx.repo),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"[stderr]\n{result.stderr}")

        output = "\n".join(output_parts) if output_parts else "(no output)"
        output += f"\n[exit code: {result.returncode}]"

        is_error = result.returncode != 0
        return output[:ctx.max_output_chars], is_error

    except subprocess.TimeoutExpired:
        output = f"Command timed out after {timeout} seconds\n[exit code: -1]"
        return output[:ctx.max_output_chars], True
    except OSError as e:
        output = f"Failed to execute command: {e}\n[exit code: -1]"
        return output[:ctx.max_output_chars], True


def _augment_path_for_runtime(env: dict[str, str], repo: Path) -> dict[str, str]:
    path_entries: list[str] = []
    local_bin = repo / ".ralph" / "node-tools" / "node_modules" / ".bin"
    if local_bin.is_dir():
        path_entries.append(str(local_bin))

    home = Path.home()
    local_user_bin = home / ".local" / "bin"
    if local_user_bin.is_dir():
        path_entries.append(str(local_user_bin))

    nvm_versions = home / ".nvm" / "versions" / "node"
    if nvm_versions.is_dir():
        candidates = sorted(nvm_versions.glob("v*/bin"), reverse=True)
        for candidate in candidates:
            if candidate.is_dir():
                path_entries.append(str(candidate))
                break

    existing = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    merged = path_entries + [p for p in existing if p not in path_entries]
    env["PATH"] = os.pathsep.join(merged)
    return env


def _run_bash_docker(command: str, timeout: int | None, ctx: ToolContext) -> tuple[str, bool]:
    timeout = min(timeout or ctx.timeout_default, ctx.timeout_max)
    repo = str(ctx.repo.resolve())
    venv_dir = "/workspace/.ralph/sandbox-venv"
    pip_cache_dir = "/workspace/.ralph/pip-cache"

    wrapped_script = (
        "set -euo pipefail; "
        "mkdir -p /workspace/.ralph; "
        "if [ ! -x "
        + shlex.quote(f"{venv_dir}/bin/python")
        + " ]; then python3 -m venv "
        + shlex.quote(venv_dir)
        + "; fi; "
        ". "
        + shlex.quote(f"{venv_dir}/bin/activate")
        + "; "
        "export PIP_CACHE_DIR="
        + shlex.quote(pip_cache_dir)
        + "; "
        "export PYTHONUNBUFFERED=1; "
        + command
    )

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--workdir",
        "/workspace",
        "--volume",
        f"{repo}:/workspace",
        "--network",
        ctx.sandbox_network,
    ]

    if os.name != "nt":
        uid = os.getuid()
        gid = os.getgid()
        docker_cmd.extend(["--user", f"{uid}:{gid}"])

    for key in ctx.sandbox_env_allowlist:
        value = os.environ.get(key)
        if value is not None and value != "":
            docker_cmd.extend(["--env", f"{key}={value}"])

    docker_cmd.extend([ctx.sandbox_docker_image, "bash", "-lc", wrapped_script])

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"[stderr]\n{result.stderr}")
        output = "\n".join(output_parts) if output_parts else "(no output)"
        output += f"\n[exit code: {result.returncode}]"
        return output[:ctx.max_output_chars], result.returncode != 0
    except FileNotFoundError:
        return (
            "Error: docker is not installed or not in PATH. "
            "Sandbox mode is docker, so bash execution is blocked (no local fallback).",
            True,
        )
    except subprocess.TimeoutExpired:
        output = f"Command timed out after {timeout} seconds\n[exit code: -1]"
        return output[:ctx.max_output_chars], True
    except OSError as e:
        output = f"Sandboxed docker run failed: {e}\n[exit code: -1]"
        return output[:ctx.max_output_chars], True


def _search_web(query: str, max_results: int | None, ctx: ToolContext) -> str:
    """Search the web via Brave Search API or DuckDuckGo Instant Answer API."""
    import json
    import os
    import urllib.parse
    import urllib.request

    if not query.strip():
        return "Error: query is empty"

    limit = max(1, min(int(max_results or 5), 10))
    q = query.strip().lower()
    curated = {
        "jest": ["https://jestjs.io/docs/getting-started", "https://www.npmjs.com/package/jest"],
        "playwright": ["https://playwright.dev/docs/intro", "https://www.npmjs.com/package/playwright"],
        "pytest": ["https://docs.pytest.org/en/stable/", "https://pypi.org/project/pytest/"],
        "typescript": ["https://www.typescriptlang.org/docs/", "https://www.npmjs.com/package/typescript"],
    }
    for key, links in curated.items():
        if key in q:
            results = [f"{key} docs — {url}" for url in links[:limit]]
            return ("Search results:\n" + "\n".join(f"- {r}" for r in results))[:ctx.max_output_chars]

    brave_api_key = (os.environ.get("BRAVE_API_KEY") or "").strip()
    provider = (os.environ.get("OPENRALPH_SEARCH_PROVIDER") or "").strip().lower()

    if not provider:
        provider = "brave" if brave_api_key else "duckduckgo"

    if provider in {"brave", "auto"} and brave_api_key:
        params = {"q": query, "count": str(limit)}
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "openralph-search/1.0",
                    "Accept": "application/json",
                    "X-Subscription-Token": brave_api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            items = data.get("web", {}).get("results", [])
            results: list[str] = []
            for item in items[:limit]:
                title = (item.get("title") or "").strip()
                desc = (item.get("description") or "").strip()
                url_item = (item.get("url") or "").strip()
                line = title or desc or url_item
                if desc and title:
                    line = f"{title}: {desc}"
                if url_item:
                    line = f"{line} — {url_item}"
                if line:
                    results.append(line)
            if results:
                output = "Search results:\n" + "\n".join(f"- {r}" for r in results)
                return output[:ctx.max_output_chars]
            if provider == "brave":
                return "No results found."
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            if provider == "brave":
                return (
                    f"Error: search request failed ({type(e).__name__}: {e}). "
                    "Check DNS/network egress from the OpenRalph runtime, API key, or disable web search."
                )

    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    }
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "openralph-search/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return (
            f"Error: search request failed ({type(e).__name__}: {e}). "
            "Check DNS/network egress from the OpenRalph runtime, or disable web search for this run."
        )

    results: list[str] = []
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        heading = data.get("Heading") or "Summary"
        results.append(f"{heading}: {abstract}")
    related = data.get("RelatedTopics") or []
    for item in related:
        if len(results) >= limit:
            break
        if "Text" in item and "FirstURL" in item:
            results.append(f"{item['Text']} — {item['FirstURL']}")
        elif "Topics" in item:
            for sub in item.get("Topics", []):
                if len(results) >= limit:
                    break
                if "Text" in sub and "FirstURL" in sub:
                    results.append(f"{sub['Text']} — {sub['FirstURL']}")

    if not results:
        return "No results found."
    output = "Search results:\n" + "\n".join(f"- {r}" for r in results[:limit])
    return output[:ctx.max_output_chars]


def _search_repo(query: str, path: str | None, max_results: int | None, ctx: ToolContext) -> str:
    query_text = (query or "").strip()
    if not query_text:
        return "Error: query is empty"
    base = path if path not in (None, "") else "."
    try:
        regex = re.escape(query_text)
        raw = _grep(regex, base, None, ctx)
        if raw.startswith("Error:") or raw == "No matches found":
            return raw
        lines = raw.splitlines()
        limit = max(1, min(int(max_results or 20), 200))
        return "\n".join(lines[:limit])
    except (ValueError, re.error) as e:
        return f"Error: repo search failed ({type(e).__name__}: {e})"


def _read_file(path: str, start_line: int | None, end_line: int | None, ctx: ToolContext) -> str:
    """Read a file with optional line range."""
    try:
        p = _resolve_path(path, ctx)

        if not p.exists():
            return f"File not found: {path}"

        if not p.is_file():
            return f"Not a file: {path}"

        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total_lines = len(lines)

        # Apply line range
        start_idx = max(0, (start_line or 1) - 1)
        end_idx = min(total_lines, end_line or total_lines)

        if start_idx >= total_lines:
            return f"Start line {start_line} exceeds file length ({total_lines} lines)"

        selected = lines[start_idx:end_idx]

        # Format with line numbers
        result_lines = []
        for i, line in enumerate(selected, start=start_idx + 1):
            result_lines.append(f"{i:4d} | {line}")

        result = "\n".join(result_lines)

        # Add truncation notice if needed
        if end_idx < total_lines and end_line is None and len(selected) >= ctx.max_file_lines:
            result += f"\n... ({total_lines - end_idx} more lines)"

        return result[:ctx.max_output_chars]

    except (ValueError, OSError) as e:
        return f"Error reading file: {e}"


def _write_file(path: str, content: str, ctx: ToolContext) -> str:
    """Write content to a file."""
    try:
        p = _resolve_path(path, ctx)

        # Create parent directories
        p.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        p.write_text(content, encoding="utf-8")

        line_count = len(content.splitlines())
        return f"Wrote {len(content)} bytes ({line_count} lines) to {path}"

    except (ValueError, OSError) as e:
        return f"Error writing file: {e}"


def _edit_file(path: str, old_text: str, new_text: str, ctx: ToolContext) -> tuple[str, bool]:
    """Apply an exact string replacement to a file."""
    try:
        p = _resolve_path(path, ctx)

        if not p.exists():
            return f"File not found: {path}", True

        content = p.read_text(encoding="utf-8")

        if old_text not in content:
            # Try to help with debugging
            lines = content.splitlines()
            old_first_line = old_text.splitlines()[0] if old_text else ""

            close_matches = difflib.get_close_matches(old_first_line, lines, n=3, cutoff=0.6)

            hint = ""
            if close_matches:
                hint = "\n\nSimilar lines found:\n" + "\n".join(f"  {m}" for m in close_matches)

            return f"old_text not found in file.{hint}", True

        count = content.count(old_text)
        if count > 1:
            return f"old_text appears {count} times in file. Make the match more specific by including surrounding context.", True

        # Apply the edit
        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")

        old_lines = len(old_text.splitlines())
        new_lines = len(new_text.splitlines())

        return f"Edited {path}: replaced {old_lines} lines with {new_lines} lines", False

    except (ValueError, OSError) as e:
        return f"Error editing file: {e}", True


def _glob(pattern: str, base: str, ctx: ToolContext) -> str:
    """Find files matching a glob pattern."""
    try:
        base_path = _resolve_path(base, ctx)

        if not base_path.exists():
            return f"Directory not found: {base}"

        if not base_path.is_dir():
            return f"Not a directory: {base}"

        matches = []
        for p in sorted(base_path.glob(pattern)):
            if _should_exclude(p, ctx):
                continue
            try:
                rel = p.relative_to(ctx.repo)
                suffix = "/" if p.is_dir() else ""
                matches.append(f"{rel}{suffix}")
            except ValueError:
                continue

            if len(matches) >= 200:
                matches.append("... (truncated, more than 200 matches)")
                break

        return "\n".join(matches) if matches else "No matches found"

    except (ValueError, OSError) as e:
        return f"Error: {e}"


def _grep(pattern: str, path: str, include: str | None, ctx: ToolContext) -> str:
    """Search for a regex pattern in files."""
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    try:
        base = _resolve_path(path, ctx)
        results = []

        if base.is_file():
            files = [base]
        else:
            if include:
                files = base.rglob(include)
            else:
                files = base.rglob("*")

        for f in files:
            if not f.is_file():
                continue
            if _should_exclude(f, ctx):
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        try:
                            rel = f.relative_to(ctx.repo)
                        except ValueError:
                            rel = f
                        results.append(f"{rel}:{i}: {line[:200]}")

                        if len(results) >= 100:
                            results.append("... (truncated, more than 100 matches)")
                            return "\n".join(results)
            except OSError:
                continue

        return "\n".join(results) if results else "No matches found"

    except (ValueError, OSError) as e:
        return f"Error: {e}"


def _list_dir(path: str, ctx: ToolContext) -> str:
    """List directory contents."""
    try:
        p = _resolve_path(path if path else ".", ctx)

        if not p.exists():
            return f"Directory not found: {path}"

        if not p.is_dir():
            return f"Not a directory: {path}"

        entries = []
        for item in sorted(p.iterdir()):
            if _should_exclude(item, ctx):
                continue

            try:
                rel = item.relative_to(ctx.repo)
            except ValueError:
                rel = item.name

            if item.is_dir():
                entries.append(f"{rel}/")
            elif item.is_symlink():
                entries.append(f"{rel} -> {item.resolve()}")
            else:
                size = item.stat().st_size
                entries.append(f"{rel} ({size} bytes)")

        return "\n".join(entries) if entries else "(empty directory)"

    except (ValueError, OSError) as e:
        return f"Error: {e}"
