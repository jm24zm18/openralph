from __future__ import annotations
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ToolStatus:
    name: str
    ok: bool
    detail: str = ""
    hint: str = ""

def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)

def _have_bin(name: str) -> bool:
    return shutil.which(name) is not None

def _have_bin_in(name: str, extra_bin_dir: Path) -> bool:
    if not extra_bin_dir.exists():
        return False
    cand = extra_bin_dir / name
    if cand.exists():
        return True
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat"):
            if (extra_bin_dir / f"{name}{ext}").exists():
                return True
    return False

def _have_python_module(module: str) -> bool:
    p = _run(["python", "-c", f"import {module}"])
    return p.returncode == 0

def _ollama_ok(host: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            _ = resp.read()
        return True, "reachable"
    except Exception as e:
        return False, f"not reachable ({e})"

def _npm_ok() -> tuple[bool, str]:
    if not _have_bin("npm"):
        return False, "npm not found on PATH"
    p = _run(["npm", "--version"])
    return (p.returncode == 0), (p.stdout.strip() or p.stderr.strip())

def _ensure_node_tools_global(pkgs: list[str]) -> tuple[bool, str]:
    ok, detail = _npm_ok()
    if not ok:
        return False, detail
    p = _run(["npm", "install", "-g", *pkgs])
    return p.returncode == 0, (p.stderr.strip() or p.stdout.strip())

def _ensure_node_tools_local(repo: Path, pkgs: list[str]) -> tuple[bool, str]:
    ok, detail = _npm_ok()
    if not ok:
        return False, detail
    tool_dir = repo / ".ralph" / "node-tools"
    tool_dir.mkdir(parents=True, exist_ok=True)
    p = _run(["npm", "install", "--prefix", str(tool_dir), *pkgs], cwd=repo)
    return p.returncode == 0, (p.stderr.strip() or p.stdout.strip())

def _venv_python(repo: Path) -> Path | None:
    for d in (repo / ".venv", repo / "venv"):
        py = d / "bin" / "python"
        if py.exists():
            return py
    return None

def _venv_has_pylsp(repo: Path) -> bool:
    for d in (repo / ".venv", repo / "venv"):
        if (d / "bin" / "pylsp").exists():
            return True
    return False

def ensure_tools(
    *,
    repo: Path,
    install: bool = True,
    node_tooling: str = "global",
    install_playwright: bool = True,
    install_playwright_browsers: bool = True,
    ollama_host: str = "http://localhost:11434",
    embed_model: str = "nomic-embed-text",
) -> list[ToolStatus]:
    results: list[ToolStatus] = []
    repo = repo.resolve()
    local_bin = repo / ".ralph" / "node-tools" / "node_modules" / ".bin"

    ok, detail = _ollama_ok(ollama_host)
    results.append(ToolStatus("ollama", ok, detail, hint=f"Start Ollama at {ollama_host}"))

    venv_py = _venv_python(repo)
    if _venv_has_pylsp(repo) or _have_bin("pylsp"):
        where = "venv" if _venv_has_pylsp(repo) else "PATH"
        results.append(ToolStatus("pylsp", True, f"found ({where})"))
    else:
        if not install:
            results.append(ToolStatus("pylsp", False, "missing", hint="python -m pip install --user python-lsp-server"))
        else:
            if venv_py is not None:
                p = _run([str(venv_py), "-m", "pip", "install", "python-lsp-server"])
                ok2 = (p.returncode == 0) and _venv_has_pylsp(repo)
                results.append(ToolStatus("pylsp", ok2, p.stderr.strip() or p.stdout.strip(), hint="Installed into venv"))
            else:
                p = _run(["python", "-m", "pip", "install", "--user", "python-lsp-server"])
                ok2 = (p.returncode == 0) and _have_bin("pylsp")
                results.append(ToolStatus("pylsp", ok2, p.stderr.strip() or p.stdout.strip()))

    node_pkgs = ["typescript", "typescript-language-server", "vscode-langservers-extracted"]
    have_tsls = _have_bin("typescript-language-server") or _have_bin_in("typescript-language-server", local_bin)
    have_html = _have_bin("vscode-html-language-server") or _have_bin_in("vscode-html-language-server", local_bin)
    have_css = _have_bin("vscode-css-language-server") or _have_bin_in("vscode-css-language-server", local_bin)

    if have_tsls and have_html and have_css:
        mode = "local" if _have_bin_in("typescript-language-server", local_bin) else "global"
        results.append(ToolStatus("node-language-servers", True, f"found ({mode})"))
    else:
        if not install:
            results.append(ToolStatus("node-language-servers", False, "missing", hint="Run: openralph init --node-tooling local"))
        else:
            if node_tooling == "local":
                ok3, msg = _ensure_node_tools_local(repo, node_pkgs)
            else:
                ok3, msg = _ensure_node_tools_global(node_pkgs)
            have_tsls = _have_bin("typescript-language-server") or _have_bin_in("typescript-language-server", local_bin)
            have_html = _have_bin("vscode-html-language-server") or _have_bin_in("vscode-html-language-server", local_bin)
            have_css = _have_bin("vscode-css-language-server") or _have_bin_in("vscode-css-language-server", local_bin)
            ok4 = ok3 and have_tsls and have_html and have_css
            results.append(ToolStatus("node-language-servers", ok4, msg))

    if install_playwright:
        have_pw = _have_python_module("playwright")
        if have_pw:
            results.append(ToolStatus("playwright-python", True, "python module found"))
        else:
            if install:
                p = _run(["python", "-m", "pip", "install", "--user", "playwright", "pytest-playwright"])
                ok5 = p.returncode == 0 and _have_python_module("playwright")
                results.append(ToolStatus("playwright-python", ok5, p.stderr.strip() or p.stdout.strip()))
            else:
                results.append(ToolStatus("playwright-python", False, "missing"))

        if install_playwright_browsers and install:
            p = _run(["python", "-m", "playwright", "install", "chromium"])
            results.append(ToolStatus("playwright-browsers-chromium", p.returncode == 0, p.stderr.strip() or p.stdout.strip()))
    return results

def doctor_report(*, repo: Path, ollama_host: str, embed_model: str, vacuum_warn_mb: float = 200.0) -> list[ToolStatus]:
    repo = repo.resolve()
    local_bin = repo / ".ralph" / "node-tools" / "node_modules" / ".bin"
    statuses: list[ToolStatus] = []

    ok, detail = _ollama_ok(ollama_host)
    statuses.append(ToolStatus("ollama", ok, detail, hint="Start Ollama or set OLLAMA_HOST"))

    oc_json = repo / "opencode.json"
    statuses.append(ToolStatus("opencode.json", oc_json.exists(), "present" if oc_json.exists() else "missing", hint="Run openralph init"))

    mem = repo / ".ralph" / "memory.sqlite3"
    if mem.exists():
        size_mb = mem.stat().st_size / (1024 * 1024)
        hint = "Run: openralph memory vacuum ." if size_mb > vacuum_warn_mb else ""
        statuses.append(ToolStatus("memory-db", True, f"present ({size_mb:.1f} MB)", hint=hint))
    else:
        statuses.append(ToolStatus("memory-db", False, "missing", hint="Run openralph init or openralph memory index"))

    venv_ok = _venv_has_pylsp(repo)
    path_ok = _have_bin("pylsp")
    statuses.append(ToolStatus("pylsp", venv_ok or path_ok,
                               "found (venv)" if venv_ok else ("found (PATH)" if path_ok else "missing")))

    have_tsls = _have_bin("typescript-language-server") or _have_bin_in("typescript-language-server", local_bin)
    have_html = _have_bin("vscode-html-language-server") or _have_bin_in("vscode-html-language-server", local_bin)
    have_css = _have_bin("vscode-css-language-server") or _have_bin_in("vscode-css-language-server", local_bin)
    statuses.append(ToolStatus("node-language-servers", have_tsls and have_html and have_css,
                               "ok" if (have_tsls and have_html and have_css) else "missing",
                               hint="Run openralph init --node-tooling local"))

    statuses.append(ToolStatus("playwright-python", _have_python_module("playwright"),
                               "found" if _have_python_module("playwright") else "missing"))
    return statuses
