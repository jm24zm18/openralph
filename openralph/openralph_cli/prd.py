from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import time
import os

from .opencode_manager import find_opencode


@dataclass
class PRDContext:
    repo_name: str
    files: dict[str, str]
    file_tree: list[str]


PRD_TEMPLATE = """# Product Requirements Document — {repo_name}
- Date: {date}
- Owner: (TBD)
- Status: Draft

## 1. Problem statement
## 2. Goals
## 3. Non-goals
## 4. Users and use cases
## 5. Requirements
### 5.1 Functional requirements
### 5.2 Non-functional requirements
### 5.3 Accessibility / i18n (if relevant)
## 6. UX notes (if relevant)
## 7. Technical considerations
## 8. Analytics / success metrics
## 9. Risks and mitigations
## 10. Milestones
## 11. Open questions
"""

CONTEXT_FILES = [
    ("README.md", "README"),
    ("README.rst", "README"),
    ("CONTRIBUTING.md", "CONTRIBUTING"),
    ("docs/README.md", "DOCS_README"),
    ("package.json", "PACKAGE_JSON"),
    ("tsconfig.json", "TSCONFIG"),
    ("pyproject.toml", "PYPROJECT"),
    ("requirements.txt", "REQUIREMENTS"),
    ("setup.py", "SETUP_PY"),
    ("Makefile", "MAKEFILE"),
    ("opencode.json", "OPENCODE_CONFIG"),
    ("opencode.jsonc", "OPENCODE_CONFIG"),
    (".github/workflows/ci.yml", "CI_WORKFLOW"),
    (".github/workflows/ci.yaml", "CI_WORKFLOW"),
]

EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph", "__pycache__", ".ruff_cache"}


def _collect_context(repo: Path) -> PRDContext:
    files: dict[str, str] = {}
    for rel_path, label in CONTEXT_FILES:
        full_path = repo / rel_path
        if full_path.exists() and full_path.is_file():
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                # Cap file size
                lines = content.split("\n")[:400]
                files[label] = "\n".join(lines)
            except Exception:
                pass

    # Collect file tree
    file_tree: list[str] = []
    try:
        for p in repo.rglob("*"):
            if p.is_file():
                rel = p.relative_to(repo)
                parts = rel.parts
                if any(ex in parts for ex in EXCLUDE_DIRS):
                    continue
                if len(parts) <= 4:
                    file_tree.append(str(rel))
                    if len(file_tree) >= 500:
                        break
    except Exception:
        pass

    return PRDContext(
        repo_name=repo.name,
        files=files,
        file_tree=sorted(file_tree)[:500],
    )


def _build_prompt(ctx: PRDContext, extra_context: str | None = None) -> str:
    today = date.today().isoformat()

    context_parts = []
    for label, content in ctx.files.items():
        context_parts.append(f"===== BEGIN {label} =====")
        context_parts.append(content)
        context_parts.append(f"===== END {label} =====")
        context_parts.append("")

    if ctx.file_tree:
        context_parts.append("===== BEGIN FILE TREE (depth 4) =====")
        context_parts.extend(ctx.file_tree)
        context_parts.append("===== END FILE TREE =====")

    context_text = "\n".join(context_parts)

    extra = f"\nADDITIONAL INPUTS:\n{extra_context}\n" if extra_context else ""
    prompt = f"""You are writing a PRD for the software repository '{ctx.repo_name}'.

Output requirements:
- Produce a single markdown document.
- Use a crisp, product-style tone (not marketing).
- Include concrete acceptance criteria and non-goals.
- Include clear user stories and success metrics.
- Be honest about unknowns: call them out as open questions.
- Keep it actionable for engineering.

Write the PRD to match this structure:

# Product Requirements Document — {ctx.repo_name}
- Date: {today}
- Owner: (TBD)
- Status: Draft

## 1. Problem statement
## 2. Goals
## 3. Non-goals
## 4. Users and use cases
## 5. Requirements
### 5.1 Functional requirements
### 5.2 Non-functional requirements
### 5.3 Accessibility / i18n (if relevant)
## 6. UX notes (if relevant)
## 7. Technical considerations
## 8. Analytics / success metrics
## 9. Risks and mitigations
## 10. Milestones
## 11. Open questions

Use the repository context below. If the repo is a developer tool, treat the 'users' as developers.

REPOSITORY CONTEXT:
{context_text}
{extra}"""
    return prompt


def generate_prd(
    repo: Path,
    output_path: Path | None = None,
    opencode_path: Path | None = None,
    extra_context: str | None = None,
    timeout: int = 300,
) -> Path:
    """Generate a PRD for the repository using OpenCode."""
    if output_path is None:
        output_path = repo / "docs" / "PRD.md"

    if opencode_path is None:
        result = find_opencode(repo)
        if result is None:
            raise RuntimeError("OpenCode not found. Run: openralph opencode install")
        opencode_path = result.path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = _collect_context(repo)
    prompt = _build_prompt(ctx, extra_context=extra_context)

    # Run OpenCode
    env = os.environ.copy()
    env.setdefault("OPENCODE_HOME", str(repo / ".opencode"))
    result = subprocess.run(
        [str(opencode_path), "run", prompt],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"OpenCode failed: {result.stderr}")

    # Write output
    output_path.write_text(result.stdout, encoding="utf-8")
    return output_path

def generate_prd_answers(repo: Path, opencode_path: Path | None = None) -> dict[str, str]:
    """Generate PRD Q&A answers using OpenCode."""
    if opencode_path is None:
        result = find_opencode(repo)
        if result is None:
            raise RuntimeError("OpenCode not found. Run: openralph opencode install")
        opencode_path = result.path

    ctx = _collect_context(repo)
    questions = "\n".join([f"- {k}: {q}" for k, q in PRD_QA_QUESTIONS])
    prompt = f"""You are drafting PRD Q&A answers for the repository '{ctx.repo_name}'.

You may use tools if needed. Your final output must be a single JSON object
with keys matching the question ids. Do not include extra commentary or markdown.
If you use tools, still end with ONLY the JSON object.

Questions:
{questions}
"""
    env = os.environ.copy()
    env.setdefault("OPENCODE_HOME", str(repo / ".opencode"))
    result = _run_opencode_with_repo_browser_shim(repo, opencode_path, prompt, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"OpenCode failed: {result.stderr}")
    try:
        return _extract_json_from_output(result.stdout)
    except Exception:
        # Retry with stricter instructions to avoid tool-call output.
        strict_prompt = f"""You are drafting PRD Q&A answers for the repository '{ctx.repo_name}'.

Do not call any tools. Output ONLY a single JSON object with keys matching the
question ids. Do not include extra commentary or markdown.

Questions:
{questions}
"""
        result = _run_opencode_with_repo_browser_shim(repo, opencode_path, strict_prompt, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"OpenCode failed: {result.stderr}")
        try:
            return _extract_json_from_output(result.stdout)
        except Exception as e:
            raise RuntimeError(f"Failed to parse PRD answers JSON: {e}") from e


def _extract_json_from_output(output: str) -> dict[str, str]:
    decoder = json.JSONDecoder()
    idx = 0
    last_valid: dict[str, str] | None = None
    required_keys = {k for k, _ in PRD_QA_QUESTIONS}
    while idx < len(output):
        start = output.find("{", idx)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(output, start)
            if isinstance(obj, dict) and required_keys.issubset(set(obj.keys())):
                last_valid = obj
            idx = end
        except Exception:
            idx = start + 1
    if last_valid is None:
        raise ValueError("No JSON object found in OpenCode output")
    return last_valid

def _parse_repo_browser_call(output: str) -> tuple[str, dict] | None:
    m = re.search(r"to=repo_browser\.(\w+)", output)
    if not m:
        m = re.search(r"\bto=(print_tree|glob|read|open_file|write|edit|search|list_dir|stat)\b", output)
    if not m:
        m = re.search(r"to=functions\.(\w+)", output)
    if not m:
        return None
    tool = m.group(1)
    if output[m.start():].startswith("to=functions."):
        tool = f"functions.{tool}"
    start = output.find("{", m.end())
    if start == -1:
        return None
    payload = output[start:]
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(payload)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return tool, obj

def _repo_browser_print_tree(repo: Path, payload: dict) -> str:
    rel_path = (payload.get("path") or "").strip()
    depth = int(payload.get("depth") or 2)
    base = repo / rel_path if rel_path else repo
    results: list[str] = []
    try:
        for p in base.rglob("*"):
            rel = p.relative_to(repo)
            if len(rel.parts) > depth:
                continue
            if p.is_dir():
                results.append(f"{rel}/")
            else:
                results.append(str(rel))
    except Exception:
        pass
    items = sorted(set(results))
    if len(items) > 200:
        return "\n".join(items[:200]) + f"\n... ({len(items) - 200} more)"
    return "\n".join(items)

def _repo_browser_glob(repo: Path, payload: dict) -> str:
    rel_path = (payload.get("path") or "").strip()
    pattern = (payload.get("pattern") or "**/*").strip()
    base = repo / rel_path if rel_path else repo
    results: list[str] = []
    try:
        for p in base.glob(pattern):
            try:
                rel = p.relative_to(repo)
            except Exception:
                rel = p
            results.append(str(rel))
    except Exception:
        pass
    items = sorted(set(results))
    if len(items) > 200:
        return "\n".join(items[:200]) + f"\n... ({len(items) - 200} more)"
    return "\n".join(items)

def _cap_prompt(text: str, limit: int = 80000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n[truncated]\n\n" + text[-half:]

def _cap_tool_result(text: str, limit: int = 20000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]\n"

def _externalize_prompt(repo: Path, prompt: str, *, limit: int = 80000) -> str:
    if len(prompt) <= limit:
        return prompt
    prompt_path = repo / ".ralph" / "prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    rel = prompt_path.relative_to(repo)
    return (
        "The full prompt is in the repo at the path below.\n"
        f"1) Call repo_browser.read on `{rel}`.\n"
        "2) Use that content as the full prompt and follow its instructions exactly.\n"
        "3) Then provide the final response.\n"
    )

def _repo_browser_read(repo: Path, payload: dict) -> str:
    rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
    line_start = int(payload.get("line_start") or 1)
    line_end = int(payload.get("line_end") or (line_start + 200))
    target = repo / rel_path if rel_path else repo
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return f"[error] Unable to read: {rel_path}"
    lines = content.splitlines()
    start_idx = max(0, line_start - 1)
    end_idx = min(len(lines), line_end)
    return "\n".join(lines[start_idx:end_idx])

def _execute_repo_browser_tool(repo: Path, tool: str, payload: dict) -> str:
    if tool == "print_tree":
        return _repo_browser_print_tree(repo, payload)
    elif tool == "list_dir":
        return _repo_browser_print_tree(repo, {"path": payload.get("path") or "", "depth": 1})
    elif tool == "stat":
        rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
        target = repo / rel_path if rel_path else repo
        try:
            stat = target.stat()
            return f"size={stat.st_size} mtime={stat.st_mtime}"
        except Exception:
            return f"[error] Unable to stat: {rel_path}"
    elif tool == "glob":
        return _repo_browser_glob(repo, payload)
    elif tool in {"read", "open_file"}:
        return _repo_browser_read(repo, payload)
    elif tool == "write":
        rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
        content = payload.get("content") or payload.get("text") or ""
        if not rel_path:
            if isinstance(payload, dict) and {"name", "version", "scripts"}.issubset(payload.keys()):
                rel_path = "package.json"
                content = json.dumps(payload, indent=2)
            else:
                return "[error] Missing path for write"
        target = repo / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            return f"[ok] wrote {rel_path}"
        except Exception:
            return f"[error] Unable to write: {rel_path}"
    elif tool == "edit":
        rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
        content = payload.get("content") or payload.get("text") or ""
        if not rel_path:
            return "[error] Missing path for edit"
        target = repo / rel_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            return f"[ok] wrote {rel_path}"
        except Exception:
            return f"[error] Unable to write: {rel_path}"
    elif tool.startswith("functions."):
        fn = tool.split(".", 1)[1]
        rel_path = (payload.get("filePath") or payload.get("path") or "").strip()
        if not rel_path:
            return f"[error] Missing path for {tool}"
        target = repo / rel_path
        if fn == "write":
            content = payload.get("content") or payload.get("text") or ""
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
                return f"[ok] wrote {rel_path}"
            except Exception:
                return f"[error] Unable to write: {rel_path}"
        if fn == "append":
            content = payload.get("content") or payload.get("text") or ""
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                existing = ""
                if target.exists():
                    existing = target.read_text(encoding="utf-8", errors="replace")
                target.write_text(existing + str(content), encoding="utf-8")
                return f"[ok] appended {rel_path}"
            except Exception:
                return f"[error] Unable to append: {rel_path}"
        if fn == "edit":
            old = payload.get("oldString")
            new = payload.get("newString")
            replace_all = bool(payload.get("replaceAll"))
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                content = ""
                if target.exists():
                    content = target.read_text(encoding="utf-8", errors="replace")
                if old is not None and new is not None:
                    if replace_all:
                        content = content.replace(old, new)
                    else:
                        content = content.replace(old, new, 1)
                elif new is not None:
                    content = content + new if content else str(new)
                target.write_text(content, encoding="utf-8")
                return f"[ok] edited {rel_path}"
            except Exception:
                return f"[error] Unable to edit: {rel_path}"
        return f"[error] Unsupported functions tool: {fn}"
    if tool == "search":
        return "[error] Web search not available in this environment."
    return f"[error] Unsupported repo_browser tool: {tool}"

def _write_tool_result_file(repo: Path, tool: str, result: str) -> Path:
    tool_dir = repo / ".ralph" / "tool-results"
    tool_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    path = tool_dir / f"{tool}-{stamp}.txt"
    path.write_text(_cap_tool_result(result, limit=50000), encoding="utf-8")
    return path

def _tool_result_content(repo: Path, payload: dict) -> str | None:
    rel = (payload.get("path") or payload.get("filePath") or "").strip()
    if not rel:
        return None
    try:
        path = (repo / rel) if not rel.startswith("/") else Path(rel)
        if not str(path).startswith(str(repo / ".ralph" / "tool-results")):
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

def _write_log_artifact(logs_dir: Path, name: str, content: str) -> None:
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.time_ns()
        path = logs_dir / f"{name}-{stamp}.txt"
        path.write_text(content, encoding="utf-8")
    except Exception:
        pass

def _run_opencode_with_repo_browser_shim(repo: Path, opencode_path: Path, prompt: str, max_shim: int = 2, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    base_prompt = prompt
    _write_log_artifact(repo / ".ralph" / "logs", "prd-prompt", prompt)
    tool_result_paths: list[str] = []
    last = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    for _ in range(max_shim + 1):
        prompt = _externalize_prompt(repo, prompt)
        prompt = _cap_prompt(prompt)
        last = subprocess.run(
            [str(opencode_path), "run", prompt],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        call = _parse_repo_browser_call((last.stdout or "") + "\n" + (last.stderr or ""))
        if call is None:
            break
        tool, payload = call
        _write_log_artifact(
            repo / ".ralph" / "logs",
            "prd-tool-call",
            f"tool={tool}\npayload={json.dumps(payload, indent=2)}\n",
        )
        if tool in {"read", "open_file"}:
            injected = _tool_result_content(repo, payload)
            if injected is not None:
                injected = _cap_tool_result(injected)
                prompt = (
                    base_prompt
                    + "\n\n# Tool result (injected)\n"
                    + injected
                    + "\n\nUse the tool result above. Do not call any tools. Provide the final response."
                )
                prompt = _cap_prompt(prompt)
                return subprocess.run(
                    [str(opencode_path), "run", prompt],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=env,
                )
        result = _execute_repo_browser_tool(repo, tool, payload)
        _write_log_artifact(
            repo / ".ralph" / "logs",
            "prd-tool-result",
            _cap_tool_result(result),
        )
        result_path = _write_tool_result_file(repo, f"repo_browser-{tool}", result)
        tool_result_paths.append(str(result_path.relative_to(repo)))
        paths_list = "\n".join(f"- {p}" for p in tool_result_paths[-3:])
        prompt = (
            base_prompt
            + "\n\nTool results saved (read these files with repo_browser.read):\n"
            + paths_list
            + "\n\nUse the tool results above. Do not call repo_browser tools."
        )
    return last


PRD_QA_QUESTIONS = [
    ("project_name", "What is the name of this project?"),
    ("problem", "What problem does this project solve? (1-2 sentences)"),
    ("users", "Who are the primary users of this project?"),
    ("goals", "What are the main goals? (comma-separated)"),
    ("non_goals", "What is explicitly out of scope? (comma-separated)"),
    ("features", "What are the key features? (comma-separated)"),
    ("non_functional", "What non-functional requirements should we enforce? (comma-separated or short sentences)"),
    ("accessibility", "What accessibility or i18n considerations are required? (comma-separated or short sentences)"),
    ("ux_notes", "What UX notes or visual style guidance should we follow? (comma-separated or short sentences)"),
    ("test_expectations", "What test expectations or coverage targets should we meet? (comma-separated or short sentences)"),
    ("deployment", "What deployment or packaging format is desired?"),
    ("risks", "What are the key risks or constraints? (comma-separated or short sentences)"),
    ("milestones", "What milestones should we target? (comma-separated or short sentences)"),
    ("tech_stack", "What technologies/languages does this use?"),
    ("success_metrics", "How will you measure success?"),
    ("open_questions", "What questions remain unanswered?"),
]


def run_prd_qa(repo: Path) -> dict[str, str]:
    """Run interactive Q&A to gather PRD info."""
    answers: dict[str, str] = {}

    print("\n[bold]PRD Q&A Session[/bold]")
    print("Answer the following questions to generate a PRD.\n")

    for key, question in PRD_QA_QUESTIONS:
        print(f"[cyan]{question}[/cyan]")
        answer = input("> ").strip()
        answers[key] = answer
        print()

    return answers


def generate_prd_from_answers(repo: Path, answers: dict[str, str], output_path: Path | None = None) -> Path:
    """Generate a PRD from Q&A answers."""
    if output_path is None:
        output_path = repo / "docs" / "PRD.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    goals = _format_bullets(answers.get("goals", ""), "- TBD")
    non_goals = _format_bullets(answers.get("non_goals", ""), "- TBD")
    features = _format_bullets(answers.get("features", ""), "- TBD")
    non_functional = _format_bullets(answers.get("non_functional", ""), "- TBD")
    accessibility = _format_bullets(answers.get("accessibility", ""), "- TBD")
    ux_notes = _format_bullets(answers.get("ux_notes", ""), "- TBD")
    test_expectations = _format_bullets(answers.get("test_expectations", ""), "- TBD")
    risks = _format_bullets(answers.get("risks", ""), "- TBD")
    milestones = _format_bullets(answers.get("milestones", ""), "- TBD")
    open_questions = _format_bullets(answers.get("open_questions", ""), "- None identified yet")

    content = f"""# Product Requirements Document — {answers.get('project_name', repo.name)}
- Date: {today}
- Owner: (TBD)
- Status: Draft

## 1. Problem statement

{answers.get('problem', 'TBD')}

## 2. Goals

{goals}

## 3. Non-goals

{non_goals}

## 4. Users and use cases

**Primary users:** {answers.get('users', 'TBD')}

## 5. Requirements

### 5.1 Functional requirements

{features}

### 5.2 Non-functional requirements

{non_functional}

### 5.3 Accessibility / i18n (if relevant)

{accessibility}

## 6. UX notes (if relevant)

{ux_notes}

## 7. Technical considerations

**Tech stack:** {answers.get('tech_stack', 'TBD')}

**Deployment:** {answers.get('deployment', 'TBD')}

**Test expectations:** {test_expectations}

## 8. Analytics / success metrics

{answers.get('success_metrics', 'TBD')}

## 9. Risks and mitigations

{risks}

## 10. Milestones

{milestones}

## 11. Open questions

{open_questions}
"""

    output_path.write_text(content, encoding="utf-8")
    return output_path


def save_prd_answers(repo: Path, answers: dict[str, str]) -> Path:
    """Save PRD Q&A answers to .ralph/prd-answers.json."""
    ralph_dir = repo / ".ralph"
    ralph_dir.mkdir(parents=True, exist_ok=True)
    answers_path = ralph_dir / "prd-answers.json"
    answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    return answers_path


def _format_bullets(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    if "\n" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return fallback
        if all(line.startswith("-") for line in lines):
            return "\n".join(lines)
        return "\n".join(f"- {line}" for line in lines)
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) <= 1:
        return f"- {text}"
    return "\n".join(f"- {p}" for p in parts)


def load_prd_answers(repo: Path) -> dict[str, str] | None:
    """Load PRD Q&A answers from .ralph/prd-answers.json."""
    answers_path = repo / ".ralph" / "prd-answers.json"
    if not answers_path.exists():
        return None
    try:
        return json.loads(answers_path.read_text(encoding="utf-8"))
    except Exception:
        return None
