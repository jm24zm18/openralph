from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
import subprocess
import difflib
import fnmatch
import re


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
        "description": "List the contents of a directory. Shows files and subdirectories with type indicators.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (relative to repo root, default: repo root)"},
            },
            "required": [],
        },
    },
]


@dataclass
class ToolContext:
    repo: Path
    timeout_default: int = 120
    timeout_max: int = 600
    max_output_chars: int = 50000
    max_file_lines: int = 2000
    exclude_patterns: list[str] = field(default_factory=lambda: [
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        "dist", "build", ".ralph", ".mypy_cache", ".pytest_cache",
    ])


def execute_tool(name: str, args: dict, ctx: ToolContext) -> tuple[str, bool]:
    """
    Execute a tool and return (result, is_error).
    """
    try:
        if name == "bash":
            return _run_bash(args["command"], args.get("timeout"), ctx), False
        elif name == "read_file":
            return _read_file(args["path"], args.get("start_line"), args.get("end_line"), ctx), False
        elif name == "write_file":
            return _write_file(args["path"], args["content"], ctx), False
        elif name == "edit_file":
            return _edit_file(args["path"], args["old_text"], args["new_text"], ctx)
        elif name == "glob":
            return _glob(args["pattern"], args.get("path", "."), ctx), False
        elif name == "grep":
            return _grep(args["pattern"], args.get("path", "."), args.get("include"), ctx), False
        elif name == "list_dir":
            return _list_dir(args.get("path", "."), ctx), False
        else:
            return f"Unknown tool: {name}", True
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}", True


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


def _run_bash(command: str, timeout: int | None, ctx: ToolContext) -> str:
    """Execute a bash command in the repository."""
    timeout = min(timeout or ctx.timeout_default, ctx.timeout_max)

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=str(ctx.repo),
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

        if result.returncode != 0:
            output = f"[exit code: {result.returncode}]\n{output}"

        return output[:ctx.max_output_chars]

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Failed to execute command: {e}"


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

    except Exception as e:
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

    except Exception as e:
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

    except Exception as e:
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

    except Exception as e:
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
            except Exception:
                continue

        return "\n".join(results) if results else "No matches found"

    except Exception as e:
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

    except Exception as e:
        return f"Error: {e}"
