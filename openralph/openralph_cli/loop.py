from __future__ import annotations
from pathlib import Path
import os
import subprocess
import re
import json
import time
import threading
from typing import Iterable

from .settings import OpenRalphSettings
from .paths import Paths
from .opencode_manager import ensure_opencode
from .memory import query_memory, index_repo
from .git_manager import (
    is_git_repo,
    ensure_branch,
    current_branch,
    checkpoint_commit,
    rollback_to_checkpoint,
    rollback_to_ref,
    is_worktree_dirty,
    worktree_status,
    write_diff_snapshot,
    update_last_green,
    head_sha,
)
from .logging import get_logger
from .features import get_feature_context, get_current_feature
from .orchestrator import run_orchestrator_iteration, build_task_prompt, mark_task_status
from .proxy import proxy_status, proxy_is_listening
from .prd import (
    PRD_QA_QUESTIONS,
    generate_prd,
    generate_prd_from_answers,
    load_prd_answers,
    run_prd_qa,
    save_prd_answers,
    generate_prd_answers,
)

def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40] or "work"

def _read_text(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""

def _resolve_repo_path(repo: Path, value: str, default: Path) -> Path:
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else repo / p

def _prompt_path(repo: Path, path: Path) -> str:
    try:
        if path.is_relative_to(repo):
            return str(path.relative_to(repo))
    except Exception:
        pass
    return str(path)

def _parse_gate(report_text: str) -> bool | None:
    m = re.search(r"Gate:\s*(PASS|FAIL)", report_text, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).upper() == "PASS"

def _detect_test_commands(repo: Path) -> tuple[str, bool]:
    hints: list[str] = []

    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if isinstance(scripts, dict) and "test" in scripts:
                hints.append(f"npm test (runs: {scripts['test']})")
        except Exception:
            hints.append("npm test (package.json detected)")

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        hints.append("pytest (pyproject.toml detected)")

    if (repo / "pytest.ini").exists():
        hints.append("pytest (pytest.ini detected)")

    if (repo / "tox.ini").exists():
        hints.append("tox (tox.ini detected)")

    if (repo / "noxfile.py").exists():
        hints.append("nox (noxfile.py detected)")

    makefile = repo / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"^test\s*:", content, flags=re.MULTILINE):
                hints.append("make test (Makefile target detected)")
        except Exception:
            pass

    if hints:
        return "Detected test commands:\n" + "\n".join(f"- {h}" for h in hints), True
    return "No test commands detected. Check for test files manually.", False

def _report_has_commands(report_text: str) -> bool:
    m = re.search(r"^## Commands run\s*$", report_text, flags=re.MULTILINE)
    if not m:
        return False
    start = m.end()
    next_header = re.search(r"^##\s+", report_text[start:], flags=re.MULTILINE)
    end = start + next_header.start() if next_header else len(report_text)
    section = report_text[start:end].strip()
    if not section:
        return False
    normalized = section.lower()
    if normalized in {"none", "n/a", "na", "not run", "no commands"}:
        return False
    return True

def _memory_hits_to_text(hits: Iterable, max_chars: int) -> str:
    parts: list[str] = []
    total = 0
    for h in hits:
        chunk = f"- {h.path}#{h.chunk_index} (score={h.score:.3f})\n{h.content[:800]}"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk) + 2
    return "\n\n".join(parts)

def _write_human_request(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")

def _ensure_logs_dir(paths: Paths) -> None:
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _worklist_needs_work(text: str) -> bool:
    if not text.strip():
        return True
    for line in text.splitlines():
        if line.strip().lower().startswith("status:"):
            return "clear" not in line.lower()
    return True

def _snapshot_repo_files(repo: Path, *, exclude_dirs: set[str], exclude_files: set[str]) -> dict[str, tuple[float, int]]:
    snapshot: dict[str, tuple[float, int]] = {}
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo)
        if rel.parts and rel.parts[0] in exclude_dirs:
            continue
        if str(rel).replace("\\", "/") in exclude_files:
            continue
        try:
            stat = path.stat()
            snapshot[str(rel)] = (stat.st_mtime, stat.st_size)
        except Exception:
            continue
    return snapshot

def _diff_repo_files(before: dict[str, tuple[float, int]], after: dict[str, tuple[float, int]]) -> set[str]:
    changed: set[str] = set()
    for path, meta in after.items():
        if path not in before:
            changed.add(path)
            continue
        if before[path] != meta:
            changed.add(path)
    return changed

def _cap_prompt(text: str, limit: int = 80000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n[truncated]\n\n" + text[-half:]

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

def _clear_human_exchange(request_path: Path, response_path: Path) -> None:
    if request_path.exists():
        request_path.unlink()
    if response_path.exists():
        response_path.unlink()

def _build_prd_handoff_prompt() -> str:
    lines = [
        "# PRD Q&A",
        "",
        "Please answer the following questions in JSON with keys matching the question ids.",
        "Example:",
        '{"project_name": "My Project", "problem": "..."}',
        "",
        "Questions:",
    ]
    for key, question in PRD_QA_QUESTIONS:
        lines.append(f"- {key}: {question}")
    return "\n".join(lines)

def _extract_json_from_response(text: str) -> dict[str, str] | None:
    try:
        import json
        return json.loads(text)
    except Exception:
        return None

def _extract_human_request_from_review(text: str) -> str | None:
    if not text:
        return None
    # Prefer a fenced block for HUMAN_REQUEST
    m = re.search(r"File:\s*`?\.ralph/HUMAN_REQUEST\.md`?.*?```(?:markdown)?\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: look for a titled section
    m = re.search(r"#\s*Human Decision Required\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0).strip()
    return None

def _git_context(repo: Path, max_chars: int = 4000) -> str:
    if not is_git_repo(repo):
        return "No git context available."
    parts: list[str] = []
    try:
        stat = subprocess.run(["git", "diff", "--stat"], cwd=str(repo), text=True, capture_output=True)
        if stat.stdout.strip():
            parts.append("Diff --stat:\n" + stat.stdout.strip())
    except Exception:
        pass
    try:
        diff = subprocess.run(["git", "diff"], cwd=str(repo), text=True, capture_output=True)
        if diff.stdout.strip():
            parts.append("Diff:\n" + diff.stdout.strip())
    except Exception:
        pass
    ctx = "\n\n".join(parts) if parts else "No diff available."
    return ctx[:max_chars]

def _parse_repo_browser_call(output: str) -> tuple[str, dict] | None:
    text = output
    m = re.search(r"to=repo_browser\.(\w+)", text)
    if not m:
        m = re.search(r"\bto=(print_tree|glob|read|open_file|write|edit|search|list_dir|stat)\b", text)
    if not m:
        m = re.search(r"to=functions\.(\w+)", text)
    if not m:
        return None
    tool = m.group(1)
    if text[m.start():].startswith("to=functions."):
        tool = f"functions.{tool}"
    start = text.find("{", m.end())
    if start == -1:
        return None
    payload = text[start:]
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

def _cap_tool_result(text: str, limit: int = 50000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]\n"

def _execute_repo_browser_tool(repo: Path, tool: str, payload: dict, settings: OpenRalphSettings) -> str:
    if tool == "print_tree":
        result = _repo_browser_print_tree(repo, payload)
    elif tool == "list_dir":
        result = _repo_browser_print_tree(repo, {"path": payload.get("path") or "", "depth": 1})
    elif tool == "stat":
        rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
        target = repo / rel_path if rel_path else repo
        try:
            stat = target.stat()
            result = f"size={stat.st_size} mtime={stat.st_mtime}"
        except Exception:
            result = f"[error] Unable to stat: {rel_path}"
    elif tool == "glob":
        result = _repo_browser_glob(repo, payload)
    elif tool in {"read", "open_file"}:
        result = _repo_browser_read(repo, payload)
    elif tool == "write":
        rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
        content = payload.get("content") or payload.get("text") or ""
        if not rel_path:
            # Heuristic fallback for common package.json write patterns
            if isinstance(payload, dict) and {"name", "version", "scripts"}.issubset(payload.keys()):
                rel_path = "package.json"
                content = json.dumps(payload, indent=2)
            else:
                result = "[error] Missing path for write"
                return result
        else:
            target = repo / rel_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
                result = f"[ok] wrote {rel_path}"
            except Exception:
                result = f"[error] Unable to write: {rel_path}"
    elif tool == "edit":
        rel_path = (payload.get("path") or payload.get("filePath") or "").strip()
        content = payload.get("content") or payload.get("text") or ""
        if not rel_path:
            result = "[error] Missing path for edit"
        else:
            target = repo / rel_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
                result = f"[ok] wrote {rel_path}"
            except Exception:
                result = f"[error] Unable to write: {rel_path}"
    elif tool == "search":
        query = (payload.get("query") or payload.get("q") or "").strip()
        if settings.web_search_enabled:
            try:
                from .web_search import web_search
                result = web_search(query, settings)
            except Exception as e:
                result = f"[error] Web search failed: {e}"
        else:
            result = "[error] Web search not enabled. Set web_search.enabled=true in config."
    elif tool.startswith("functions."):
        fn = tool.split(".", 1)[1]
        rel_path = (payload.get("filePath") or payload.get("path") or "").strip()
        if not rel_path:
            result = f"[error] Missing path for {tool}"
            return result
        target = repo / rel_path
        if fn == "write":
            content = payload.get("content") or payload.get("text") or ""
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
                result = f"[ok] wrote {rel_path}"
            except Exception:
                result = f"[error] Unable to write: {rel_path}"
        elif fn == "append":
            content = payload.get("content") or payload.get("text") or ""
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                existing = ""
                if target.exists():
                    existing = target.read_text(encoding="utf-8", errors="replace")
                target.write_text(existing + str(content), encoding="utf-8")
                result = f"[ok] appended {rel_path}"
            except Exception:
                result = f"[error] Unable to append: {rel_path}"
        elif fn == "edit":
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
                result = f"[ok] edited {rel_path}"
            except Exception:
                result = f"[error] Unable to edit: {rel_path}"
        else:
            result = f"[error] Unsupported functions tool: {fn}"
    else:
        result = f"[error] Unsupported repo_browser tool: {tool}"
    return result

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

def _run_opencode_with_repo_browser_shim(
    repo: Path,
    oc_path: Path,
    prompt: str,
    env: dict[str, str],
    settings: OpenRalphSettings,
    *,
    max_shim: int = 2,
    label: str = "stage",
) -> tuple[str, str, int]:
    base_prompt = prompt
    tool_result_paths: list[str] = []
    last_stdout = ""
    last_stderr = ""
    last_code = 0
    for _ in range(max_shim + 1):
        prompt = _externalize_prompt(repo, prompt)
        prompt = _cap_prompt(prompt)
        start = time.time()
        stop = threading.Event()

        def _heartbeat() -> None:
            while not stop.wait(30):
                elapsed = int(time.time() - start)
                print(f"[openralph] {label} running... {elapsed}s elapsed")

        t = threading.Thread(target=_heartbeat, daemon=True)
        t.start()
        p = subprocess.run([str(oc_path), "run", prompt], cwd=str(repo), env=env, text=True, capture_output=True)
        stop.set()
        elapsed = int(time.time() - start)
        print(f"[openralph] {label} finished in {elapsed}s (rc={p.returncode})")
        last_stdout = p.stdout or ""
        last_stderr = p.stderr or ""
        last_code = p.returncode
        if not (last_stdout.strip() or last_stderr.strip()):
            get_logger("loop").warning("OpenCode returned empty output for %s stage", label)
        if "to=repo_browser" in last_stderr and "to=repo_browser" not in last_stdout:
            get_logger("loop").debug("OpenCode tool call emitted to stderr in %s stage", label)
        call = _parse_repo_browser_call((last_stdout or "") + "\n" + (last_stderr or ""))
        if call is None:
            break
        tool, payload = call
        if tool in {"read", "open_file"}:
            injected = _tool_result_content(repo, payload)
            if injected is not None:
                prompt = (
                    base_prompt
                    + "\n\n# Tool result (injected)\n"
                    + injected
                    + "\n\nUse the tool result above. Do not call any tools. Provide the final response."
                )
                start = time.time()
                stop = threading.Event()

                def _heartbeat_injected() -> None:
                    while not stop.wait(30):
                        elapsed = int(time.time() - start)
                        print(f"[openralph] {label} (injected) running... {elapsed}s elapsed")

                t = threading.Thread(target=_heartbeat_injected, daemon=True)
                t.start()
                p = subprocess.run([str(oc_path), "run", prompt], cwd=str(repo), env=env, text=True, capture_output=True)
                stop.set()
                elapsed = int(time.time() - start)
                print(f"[openralph] {label} (injected) finished in {elapsed}s (rc={p.returncode})")
                return (p.stdout or ""), (p.stderr or ""), p.returncode
        result = _execute_repo_browser_tool(repo, tool, payload, settings)
        result_path = _write_tool_result_file(repo, f"repo_browser-{tool}", result)
        tool_result_paths.append(str(result_path.relative_to(repo)))
        paths_list = "\n".join(f"- {p}" for p in tool_result_paths[-3:])
        prompt = (
            base_prompt
            + "\n\nTool results saved (read these files with repo_browser.read):\n"
            + paths_list
            + "\n\nUse the tool results above. Do not call repo_browser tools."
        )
    return last_stdout, last_stderr, last_code

def _auto_respond_to_human_request(
    repo: Path,
    oc_path: Path,
    request_text: str,
    context: str,
) -> str:
    response_prompt = (
        "You are responding to HUMAN_REQUEST for a software project.\n\n"
        "Rules:\n"
        "- Answer each question directly and concisely.\n"
        "- If a choice is required, pick the default that best enables progress.\n"
        "- If information is missing, make a reasonable assumption and state it.\n"
        "- Do not call any tools.\n"
        "- Output plain text suitable for .ralph/HUMAN_RESPONSE.md.\n\n"
        "HUMAN_REQUEST:\n"
        f"{request_text}\n\n"
        "Context:\n"
        f"{context}\n"
    )
    try:
        p = subprocess.run([str(oc_path), "run", response_prompt], cwd=str(repo), text=True, capture_output=True)
        if p.returncode == 0 and (p.stdout or "").strip():
            return p.stdout.strip() + "\n"
    except Exception:
        pass
    return "Assumption: proceed with sensible defaults to unblock implementation.\n"

def run_loop(repo: Path, prompt: str, *, max_iters: int, settings: OpenRalphSettings | None = None) -> bool:
    log = get_logger("loop")
    repo = repo.resolve()
    settings = settings or OpenRalphSettings.load(repo)
    paths = Paths.for_repo(repo)
    paths.logs.mkdir(parents=True, exist_ok=True)

    log.info("Starting run loop: repo=%s, max_iters=%d", repo, max_iters)
    log.debug("Settings: ollama_host=%s, embed_model=%s", settings.ollama_host, settings.embed_model)

    # best-effort index at start
    try:
        log.debug("Indexing repository at start")
        index_repo(
            repo,
            paths.memory_db,
            settings.ollama_host,
            settings.embed_model,
            include_exts=set(settings.memory_include_exts),
            exclude_dirs=set(settings.memory_exclude_dirs),
            exclude_names=set(settings.memory_exclude_names),
            chunk_chars=settings.memory_chunk_chars,
            chunk_overlap=settings.memory_chunk_overlap,
        )
        log.debug("Initial indexing complete")
    except Exception as e:
        log.warning("Initial memory indexing failed (continuing): %s", e, exc_info=True)

    if is_git_repo(repo):
        if is_worktree_dirty(repo):
            log.warning("Git worktree has uncommitted changes before loop start")
            status = worktree_status(repo)
            if status:
                log.debug("Worktree status:\n%s", status)
        branch_name = _slugify(prompt)
        log.info("Ensuring git branch: %s", branch_name)
        ensure_branch(repo, branch_name)

    oc = ensure_opencode(repo, auto_install=settings.opencode_auto_install, version=settings.opencode_version)
    log.info("Using OpenCode: %s", oc.path)
    env = os.environ.copy()
    env.setdefault("OPENCODE_HOME", str(repo / ".opencode"))
    env.setdefault("OPENCODE_EXPERIMENTAL", "true")
    env.setdefault("OPENCODE_EXPERIMENTAL_LSP_TOOL", "true")
    log.debug("OpenCode env: OPENCODE_HOME=%s OPENCODE_EXPERIMENTAL=%s OPENCODE_EXPERIMENTAL_LSP_TOOL=%s",
              env.get("OPENCODE_HOME"), env.get("OPENCODE_EXPERIMENTAL"), env.get("OPENCODE_EXPERIMENTAL_LSP_TOOL"))
    if settings.proxy_enabled:
        running, pid = proxy_status(paths.proxy_pid, settings.proxy_listen_port)
        listening = proxy_is_listening(settings.proxy_listen_port)
        log.debug(
            "Proxy enabled: running=%s pid=%s listening=%s target=%s:%s model=%s provider=%s",
            running,
            pid,
            listening,
            settings.proxy_target_host,
            settings.proxy_target_port,
            settings.proxy_target_model,
            settings.proxy_provider_name,
        )

    test_report = _resolve_repo_path(repo, settings.loop_test_report, paths.test_report)
    review_report = _resolve_repo_path(repo, settings.loop_review_report, paths.review_report)
    final_report = _resolve_repo_path(repo, settings.loop_final_report, paths.final_report)

    if paths.done_marker.exists():
        # Only honor DONE marker if it was created for the same prompt
        done_content = _read_text(paths.done_marker, max_chars=10000) or ""
        done_prompt = ""
        for line in done_content.splitlines():
            if line.startswith("prompt:"):
                done_prompt = line[7:]
                break
        if done_prompt and done_prompt != prompt:
            log.info("DONE marker from different prompt; clearing for new task")
            try:
                paths.done_marker.unlink()
            except Exception:
                pass
        elif not done_prompt:
            # Old-style DONE marker without prompt - clear it for safety
            log.info("DONE marker has no prompt info; clearing for safety")
            try:
                paths.done_marker.unlink()
            except Exception:
                pass
        else:
            last_test = _read_text(test_report)
            gate = _parse_gate(last_test)
            if gate:
                log.info("DONE marker present with PASS gate; stopping loop")
                return False
            log.warning("DONE marker present but gate not PASS; ignoring and removing DONE")
            try:
                paths.done_marker.unlink()
            except Exception:
                pass

    # Ensure PRD exists before loop
    if not paths.prd.exists():
        mode = settings.loop_prd_qa_mode
        log.info("PRD missing; running PRD Q&A mode: %s", mode)
        if mode == "interactive":
            answers = run_prd_qa(repo)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
        elif mode == "handoff":
            if not paths.human_response.exists():
                _write_human_request(paths.human_request, _build_prd_handoff_prompt())
                if settings.loop_human_response == "auto":
                    auto = generate_prd_answers(repo, oc.path)
                    save_prd_answers(repo, auto)
                    generate_prd_from_answers(repo, auto, paths.prd)
                    _clear_human_exchange(paths.human_request, paths.human_response)
                else:
                    log.warning("Wrote PRD questions to HUMAN_REQUEST; awaiting response")
                    return True
            if paths.human_response.exists():
                data = _extract_json_from_response(_read_text(paths.human_response, max_chars=20000))
                if not data:
                    log.warning("HUMAN_RESPONSE did not contain valid JSON for PRD answers")
                    return True
                save_prd_answers(repo, data)
                generate_prd_from_answers(repo, data, paths.prd)
                _clear_human_exchange(paths.human_request, paths.human_response)
        elif mode == "auto-then-handoff":
            answers = generate_prd_answers(repo, oc.path)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
            _write_human_request(paths.human_request, "Please review the generated PRD and list any changes.")
            log.warning("PRD drafted; awaiting review via HUMAN_REQUEST")
            return True
        elif mode == "auto":
            answers = generate_prd_answers(repo, oc.path)
            save_prd_answers(repo, answers)
            generate_prd_from_answers(repo, answers, paths.prd)
        else:
            log.warning("Unknown PRD QA mode: %s", mode)
    if paths.prd.exists() and "generate prd" in prompt.lower():
        prompt = f"Implement the entire PRD in {_prompt_path(repo, paths.prd)}"
        log.info("PRD present; switching to implementation prompt: %s", prompt)

    gate_fails = 0
    review_every = 2
    for i in range(1, max_iters + 1):
        log.info("=== Iteration %d/%d ===", i, max_iters)
        _ensure_logs_dir(paths)
        if paths.human_request.exists() and not paths.human_response.exists():
            if settings.loop_human_response == "auto":
                request_text = _read_text(paths.human_request, max_chars=8000)
                prd_excerpt = _read_text(paths.prd, max_chars=3000)
                context = f"Prompt: {prompt}\n\nPRD excerpt:\n{prd_excerpt}\n"
                auto_resp = _auto_respond_to_human_request(repo, oc.path, request_text, context)
                paths.human_response.write_text(auto_resp, encoding="utf-8")
            else:
                log.warning("Awaiting HUMAN_RESPONSE before continuing")
                return True

        # PRD refresh cadence
        if settings.loop_prd_refresh_every > 0 and i % settings.loop_prd_refresh_every == 0:
            log.info("PRD refresh triggered on iteration %d", i)
            if settings.loop_prd_refresh_mode == "ask":
                if not paths.human_response.exists():
                    _write_human_request(paths.human_request, "Provide PRD deltas or confirm no changes needed.")
                    if settings.loop_human_response == "auto":
                        paths.human_response.write_text("No PRD changes.\n", encoding="utf-8")
                    else:
                        log.warning("PRD refresh awaiting HUMAN_RESPONSE")
                        return True
                updates = _read_text(paths.human_response, max_chars=20000)
                _clear_human_exchange(paths.human_request, paths.human_response)
                try:
                    answers = load_prd_answers(repo)
                    if answers:
                        if updates.strip():
                            generate_prd_from_answers(repo, answers, paths.prd)
                            generate_prd(repo, paths.prd, oc.path, extra_context=updates)
                        else:
                            generate_prd_from_answers(repo, answers, paths.prd)
                    else:
                        generate_prd(repo, paths.prd, oc.path, extra_context=updates)
                except Exception as e:
                    log.warning("PRD refresh failed: %s", e, exc_info=True)
            else:
                try:
                    answers = load_prd_answers(repo)
                    if answers:
                        generate_prd_from_answers(repo, answers, paths.prd)
                    else:
                        generate_prd(repo, paths.prd, oc.path)
                except Exception as e:
                    log.warning("PRD refresh failed: %s", e, exc_info=True)

        current_task = None
        feature_ctx = get_feature_context(repo)
        feature_in_prompt = False
        if settings.orchestrator_enabled:
            current_task = run_orchestrator_iteration(repo, settings, oc_path=oc.path, iteration=i)
            if current_task is None:
                log.info("Orchestrator reports no remaining tasks; stopping loop")
                break

        worklist_text = _read_text(paths.worklist, max_chars=8000)
        if "to=repo_browser." in worklist_text:
            worklist_text = ""
        worklist_needs_work = _worklist_needs_work(worklist_text)
        iter_prompt = prompt
        if current_task is not None:
            iter_prompt = build_task_prompt(current_task, feature_ctx)
            feature_in_prompt = True
        if current_task is None and worklist_needs_work and worklist_text.strip():
            iter_prompt = f"Implement the items in {_prompt_path(repo, paths.worklist)}"

        mem = ""
        try:
            log.debug("Querying memory with prompt (k=%d)", settings.memory_k)
            path_boosts = list(settings.memory_path_boosts) + [("docs/PRD.md", 1.3), ("docs/features/", 1.2)]
            current_feature = get_current_feature(repo)
            if current_feature:
                try:
                    rel = current_feature.relative_to(repo).as_posix()
                except Exception:
                    rel = str(current_feature)
                if rel and not rel.endswith("/"):
                    rel = rel + "/"
                if rel:
                    path_boosts.append((rel, 1.5))
            hits = query_memory(
                paths.memory_db,
                settings.ollama_host,
                settings.embed_model,
                iter_prompt,
                k=settings.memory_k,
                path_boosts=path_boosts,
            )
            if hits:
                log.debug("Memory query returned %d hits", len(hits))
                mem = _memory_hits_to_text(hits, settings.memory_inject_max_chars)
            else:
                log.debug("Memory query returned no hits")
        except Exception as e:
            log.warning("Memory query failed (continuing): %s", e, exc_info=True)

        combined = iter_prompt
        if mem:
            combined += "\n\n# Retrieved project memory (top hits)\n" + mem
        if feature_ctx and not feature_in_prompt:
            combined += "\n\n# Current feature context\n" + feature_ctx
        if worklist_text.strip():
            combined += "\n\n# Worklist\n" + worklist_text
        if test_report.exists():
            combined += "\n\n# Prior Test Report\n" + _read_text(test_report, max_chars=8000)
        if review_report.exists():
            combined += "\n\n# Prior Review Report\n" + _read_text(review_report, max_chars=8000)
        if paths.human_response.exists():
            combined += "\n\n# Human Response\n" + _read_text(paths.human_response, max_chars=8000)
            _clear_human_exchange(paths.human_request, paths.human_response)
        final_rel = _prompt_path(repo, final_report)
        rules = [
            "Rules:",
            "- Address test failures first.",
            "- Keep PRD and feature specs aligned.",
            "- If a PRD exists, implement it in code (not just edits to PRD).",
            "- If you need a decision, write to .ralph/HUMAN_REQUEST.md and stop.",
            f"- When complete: write {final_rel} and create .ralph/DONE.",
        ]
        if worklist_needs_work and worklist_text.strip():
            rules.insert(1, "- The worklist is the source of truth; implement it first.")
            rules.insert(2, "- Do not edit docs/PRD.md while worklist is non-empty.")
        combined += "\n\n" + "\n".join(rules)

        builder_log = paths.logs / f"builder-iter-{i}.log"
        log.debug("Running OpenCode builder: %s", oc.path)
        print("[openralph] Starting builder stage")
        before_builder = _snapshot_repo_files(
            repo,
            exclude_dirs={".ralph", ".opencode", ".git"},
            exclude_files={"docs/PRD.md"},
        )
        b_out, b_err, b_code = _run_opencode_with_repo_browser_shim(repo, oc.path, combined, env, settings, label="builder")
        _ensure_logs_dir(paths)
        builder_log.write_text((b_out or "") + "\n" + (b_err or ""), encoding="utf-8")
        log.debug("Builder output written to: %s", builder_log)
        if b_code != 0:
            log.warning("Builder stage exited with non-zero return code: %d", b_code)
        after_builder = _snapshot_repo_files(
            repo,
            exclude_dirs={".ralph", ".opencode", ".git"},
            exclude_files={"docs/PRD.md"},
        )
        changed_non_prd = _diff_repo_files(before_builder, after_builder)
        if not changed_non_prd:
            strict = (
                combined
                + "\n\nHard rule: do not edit docs/PRD.md or any files under .ralph.\n"
                "You may read docs/PRD.md. Do not ask the user to provide it.\n"
                "You must create real project files and implementation code now.\n"
                "If decisions are needed, still create minimal scaffolding and note assumptions.\n"
            )
            log.warning("Builder made no non-PRD changes; retrying with strict prompt")
            print("[openralph] Builder made no non-PRD changes; retrying")
            b_out, b_err, b_code = _run_opencode_with_repo_browser_shim(repo, oc.path, strict, env, settings, label="builder")
            _ensure_logs_dir(paths)
            builder_log.write_text((b_out or "") + "\n" + (b_err or ""), encoding="utf-8")
            log.debug("Builder retry output written to: %s", builder_log)
        if paths.human_request.exists() and not paths.human_response.exists():
            if settings.loop_human_response == "auto":
                request_text = _read_text(paths.human_request, max_chars=8000)
                prd_excerpt = _read_text(paths.prd, max_chars=3000)
                context = f"Prompt: {prompt}\n\nPRD excerpt:\n{prd_excerpt}\n"
                auto_resp = _auto_respond_to_human_request(repo, oc.path, request_text, context)
                paths.human_response.write_text(auto_resp, encoding="utf-8")
            else:
                log.warning("Builder requested human input; stopping loop")
                return True

        # Test stage
        git_ctx = _git_context(repo)
        test_report_iter = test_report.parent / f"TEST_REPORT.iter-{i}.md"
        test_hints, test_hints_found = _detect_test_commands(repo)
        test_prompt = (
            "You are the Testing Agent.\n\n"
            "YOUR PRIMARY JOB IS TO EXECUTE TESTS. You MUST run the test command, not just read files.\n\n"
            "Repo rules:\n"
            "- Prefer running fast checks first.\n"
            "- You MUST run the detected test command(s) using bash.\n"
            "- Keep commands minimal and relevant.\n"
            "- If dependencies are missing, say what's needed and propose the smallest install steps.\n\n"
            "Gate rule:\n"
            "- If test commands exist (package.json scripts.test, pyproject.toml, pytest.ini, etc.) but no tests were executed, Gate: FAIL.\n"
            "- If no test infrastructure exists at all, Gate: PASS with recommendation to add tests.\n"
            "- If tests ran and passed, Gate: PASS.\n"
            "- If tests ran and failed, Gate: FAIL.\n\n"
            "Test command hints:\n"
            "{test_hints}\n\n"
            "Write a markdown report to the file: {report_path}\n"
            "It must include a line: Gate: PASS or Gate: FAIL.\n\n"
            "Include sections:\n"
            "# Test Report\n"
            "## Commands run\n"
            "## Results\n"
            "## Failures (if any)\n"
            "## Recommended next actions\n\n"
            "Feature context:\n"
            "{feature}\n\n"
            "Recent changes:\n"
            "{git_ctx}\n\n"
            "Test policy (if present):\n"
            "{test_policy}\n"
        ).format(
            report_path=_prompt_path(repo, test_report_iter),
            git_ctx=git_ctx,
            test_policy=_read_text(repo / ".ralph" / "test-policy.md", max_chars=4000) or "No test policy found.",
            test_hints=test_hints,
            feature=feature_ctx or "No current feature set.",
        )
        test_log = paths.logs / f"test-iter-{i}.log"
        print("[openralph] Starting test stage")
        t_out, t_err, t_code = _run_opencode_with_repo_browser_shim(repo, oc.path, test_prompt, env, settings, label="test")
        _ensure_logs_dir(paths)
        test_log.write_text((t_out or "") + "\n" + (t_err or ""), encoding="utf-8")
        log.debug("Test output written to: %s", test_log)
        if t_code != 0:
            log.warning("Test stage exited with non-zero return code: %d", t_code)
        if test_report_iter.exists():
            test_report.parent.mkdir(parents=True, exist_ok=True)
            test_report.write_text(test_report_iter.read_text(encoding="utf-8"), encoding="utf-8")
        elif (t_out or "").strip():
            test_report.parent.mkdir(parents=True, exist_ok=True)
            test_report_iter.write_text(t_out, encoding="utf-8")
            test_report.write_text(t_out, encoding="utf-8")
        if test_report_iter.exists() and test_hints_found:
            report_text = _read_text(test_report_iter, max_chars=8000)
            if not _report_has_commands(report_text):
                enforced = (
                    report_text.strip()
                    + "\n\n## Gate enforcement\n"
                    + "Detected test commands but no executed commands were reported.\n"
                    + "Gate: FAIL\n"
                )
                test_report_iter.write_text(enforced, encoding="utf-8")
                test_report.write_text(enforced, encoding="utf-8")

        if paths.human_request.exists() and not paths.human_response.exists():
            if settings.loop_human_response == "auto":
                request_text = _read_text(paths.human_request, max_chars=8000)
                prd_excerpt = _read_text(paths.prd, max_chars=3000)
                context = f"Prompt: {prompt}\n\nPRD excerpt:\n{prd_excerpt}\n"
                auto_resp = _auto_respond_to_human_request(repo, oc.path, request_text, context)
                paths.human_response.write_text(auto_resp, encoding="utf-8")
            else:
                log.warning("Test agent requested human input; stopping loop")
                return True

        builder_made_changes = bool(changed_non_prd)
        do_review = builder_made_changes and ((i == 1) or (i % review_every == 0) or (not worklist_needs_work))
        if not builder_made_changes:
            log.debug("Skipping review/compliance: no code changes in this iteration")
        if do_review:
            # Review stage
            feature_ctx = get_feature_context(repo)
            prd_excerpt = _read_text(paths.prd, max_chars=4000) if paths.prd.exists() else "No PRD found."
            review_prompt = (
                "You are the Product/Review Agent.\n\n"
                "Your job:\n"
                "- Check alignment with docs/PRD.md and current feature specs.\n"
                "- Identify UX/product gaps, missing acceptance criteria, and edge cases.\n"
                "- Suggest improvements in plain language.\n\n"
                "Context:\n"
                "PRD (excerpt):\n"
                "{prd}\n\n"
                "Feature context:\n"
                "{feature}\n\n"
                "Test report (if present):\n"
                "{test_report}\n\n"
                "Recent changes:\n"
                "{git_ctx}\n\n"
                "Write a markdown report to the file: {report_path}\n"
                "Include sections:\n"
                "# Review Report\n"
                "## PRD alignment\n"
                "## User-impact / UX notes\n"
                "## Risks / edge cases\n"
                "## Acceptance criteria checklist\n"
                "## Questions (if any)\n\n"
                "If a decision is required, write .ralph/HUMAN_REQUEST.md and stop.\n"
            ).format(
                prd=prd_excerpt,
                feature=feature_ctx or "No current feature set.",
                test_report=_read_text(test_report_iter, max_chars=4000)
                if test_report_iter.exists()
                else "No test report found.",
                git_ctx=git_ctx,
                report_path=_prompt_path(repo, review_report),
            )
            review_log = paths.logs / f"review-iter-{i}.log"
            print("[openralph] Starting review stage")
            r_out, r_err, r_code = _run_opencode_with_repo_browser_shim(repo, oc.path, review_prompt, env, settings, label="review")
            _ensure_logs_dir(paths)
            review_log.write_text((r_out or "") + "\n" + (r_err or ""), encoding="utf-8")
            log.debug("Review output written to: %s", review_log)
            if r_code != 0:
                log.warning("Review stage exited with non-zero return code: %d", r_code)
            if not review_report.exists() and (r_out or "").strip():
                review_report.parent.mkdir(parents=True, exist_ok=True)
                review_report.write_text(r_out, encoding="utf-8")

            if not paths.human_request.exists() and review_report.exists():
                extracted = _extract_human_request_from_review(_read_text(review_report, max_chars=12000))
                if extracted:
                    _write_human_request(paths.human_request, extracted)

            if paths.human_request.exists() and not paths.human_response.exists():
                if settings.loop_human_response == "auto":
                    request_text = _read_text(paths.human_request, max_chars=8000)
                    prd_excerpt = _read_text(paths.prd, max_chars=3000)
                    context = f"Prompt: {prompt}\n\nPRD excerpt:\n{prd_excerpt}\n"
                    auto_resp = _auto_respond_to_human_request(repo, oc.path, request_text, context)
                    paths.human_response.write_text(auto_resp, encoding="utf-8")
                else:
                    log.warning("Review agent requested human input; stopping loop")
                    return True

            # PRD compliance stage
            compliance_prompt = (
                "You are the PRD Compliance Agent.\n\n"
                "Your job:\n"
                "- Compare docs/PRD.md to the actual repo implementation.\n"
                "- Identify missing features, bugs, and gaps.\n"
                "- Produce a concise, actionable worklist.\n\n"
                "Output requirements:\n"
                "- Write to the file: {worklist_path}\n"
                "- Include a top line: Status: CLEAR or Status: NEEDS_WORK\n"
                "- Provide a short summary.\n"
                "- Provide an ordered list of tasks with file paths or commands.\n"
                "- If everything is done, set Status: CLEAR and list no tasks.\n\n"
                "Context:\n"
                "PRD (excerpt):\n{prd}\n\n"
                "Review report (if present):\n{review}\n\n"
                "Recent changes:\n{git_ctx}\n"
            ).format(
                worklist_path=_prompt_path(repo, paths.worklist),
                prd=_read_text(paths.prd, max_chars=5000) if paths.prd.exists() else "No PRD found.",
                review=_read_text(review_report, max_chars=5000) if review_report.exists() else "No review report found.",
                git_ctx=git_ctx,
            )
            compliance_log = paths.logs / f"compliance-iter-{i}.log"
            print("[openralph] Starting compliance stage")
            c_out, c_err, c_code = _run_opencode_with_repo_browser_shim(repo, oc.path, compliance_prompt, env, settings, label="compliance")
            _ensure_logs_dir(paths)
            compliance_log.write_text((c_out or "") + "\n" + (c_err or ""), encoding="utf-8")
            log.debug("Compliance output written to: %s", compliance_log)
            if c_code != 0:
                log.warning("Compliance stage exited with non-zero return code: %d", c_code)
            if not paths.worklist.exists() and (c_out or "").strip():
                if re.search(r"^Status:", c_out, flags=re.MULTILINE):
                    paths.worklist.parent.mkdir(parents=True, exist_ok=True)
                    paths.worklist.write_text(c_out, encoding="utf-8")

        gate_report = _read_text(test_report_iter, max_chars=8000)
        gate = _parse_gate(gate_report)
        gates_ok = bool(gate)
        log.info("Iteration %d: test gate=%s", i, gate)
        if gates_ok:
            gate_fails = 0
            if is_git_repo(repo):
                try:
                    log.info("Creating checkpoint commit for iteration %d", i)
                    sha = checkpoint_commit(repo, f"openralph: checkpoint - iter {i}")
                    if not sha:
                        sha = head_sha(repo)
                    if sha:
                        update_last_green(repo, sha, paths.last_green)
                except Exception as e:
                    log.warning("Checkpoint commit failed: %s", e, exc_info=True)
            worklist_text = _read_text(paths.worklist, max_chars=8000)
            if current_task is not None and not _worklist_needs_work(worklist_text):
                mark_task_status(repo, current_task.id, "done")
            if final_report.exists() and not paths.done_marker.exists() and not _worklist_needs_work(worklist_text):
                try:
                    # Store prompt in DONE marker so we only honor it for the same task
                    paths.done_marker.write_text(f"done\nprompt:{prompt}\n", encoding="utf-8")
                    log.info("FINAL.md present; wrote DONE marker")
                except Exception:
                    log.warning("Failed to write DONE marker", exc_info=True)
            if paths.done_marker.exists():
                log.info("DONE marker found with PASS gate; stopping loop")
                break
            log.info("Gate PASS but no DONE marker; continuing loop")
        else:
            gate_fails += 1
            log.warning("Gate failed (count=%d/%d)", gate_fails, settings.loop_max_gate_fails)
            if b_err:
                log.debug("OpenCode stderr: %s", b_err[:500])
            if is_git_repo(repo):
                diff_path = paths.logs / f"gate-fail-iter-{i}.diff"
                write_diff_snapshot(repo, diff_path)
            if settings.loop_rollback_on_gate_fail and is_git_repo(repo) and gate_fails >= settings.loop_max_gate_fails:
                log.info("Rolling back after %d gate failures", gate_fails)
                if paths.last_green.exists():
                    rollback_to_ref(repo, paths.last_green.read_text(encoding="utf-8").strip())
                else:
                    rollback_to_checkpoint(repo)
                gate_fails = 0

        # best-effort reindex
        try:
            log.debug("Re-indexing repository after iteration %d", i)
            index_repo(
                repo,
                paths.memory_db,
                settings.ollama_host,
                settings.embed_model,
                include_exts=set(settings.memory_include_exts),
                exclude_dirs=set(settings.memory_exclude_dirs),
                exclude_names=set(settings.memory_exclude_names),
                chunk_chars=settings.memory_chunk_chars,
                chunk_overlap=settings.memory_chunk_overlap,
            )
        except Exception as e:
            log.warning("Re-indexing failed (continuing): %s", e, exc_info=True)
    else:
        log.warning("Run loop exhausted max_iters=%d without success", max_iters)
    return False
