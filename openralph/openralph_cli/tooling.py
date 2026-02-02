from __future__ import annotations
import os
import shutil
import socket
import subprocess
import sys
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

def _find_system_python() -> str:
    """Find a system Python interpreter for --user installs.

    When running inside pipx/venv, sys.executable can't do --user installs.
    Find python3 or python on the system PATH instead.
    """
    for name in ("python3", "python"):
        py = shutil.which(name)
        if py:
            # Verify it's not inside a venv by checking for --user support
            p = subprocess.run(
                [py, "-c", "import site; print(site.ENABLE_USER_SITE)"],
                capture_output=True, text=True
            )
            if p.returncode == 0 and p.stdout.strip() == "True":
                return py
    # Fallback to sys.executable if nothing better found
    return sys.executable

def _is_externally_managed_python(py: str) -> bool:
    """Check if Python is externally managed (PEP 668)."""
    p = subprocess.run(
        [py, "-c", "import sysconfig; print(sysconfig.get_path('stdlib'))"],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        return False
    stdlib = Path(p.stdout.strip())
    marker = stdlib / "EXTERNALLY-MANAGED"
    return marker.exists()

def _get_tools_venv(repo: Path) -> Path:
    """Get the path to the tools venv in .ralph."""
    return repo / ".ralph" / "tools-venv"

def _get_tools_venv_python(repo: Path) -> str | None:
    """Get the Python interpreter from the tools venv if it exists."""
    venv = _get_tools_venv(repo)
    if os.name == "nt":
        py = venv / "Scripts" / "python.exe"
    else:
        py = venv / "bin" / "python"
    if py.exists():
        return str(py)
    return None

def _ensure_tools_venv(repo: Path) -> str:
    """Create a tools venv if needed and return the Python path."""
    venv_py = _get_tools_venv_python(repo)
    if venv_py:
        return venv_py

    venv = _get_tools_venv(repo)
    system_py = _find_system_python()
    subprocess.run([system_py, "-m", "venv", str(venv)], check=True)

    if os.name == "nt":
        return str(venv / "Scripts" / "python.exe")
    return str(venv / "bin" / "python")

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

def _have_python_module(module: str, repo: Path | None = None) -> bool:
    # Check in tools venv first if repo is provided
    if repo:
        tools_py = _get_tools_venv_python(repo)
        if tools_py:
            p = _run([tools_py, "-c", f"import {module}"])
            if p.returncode == 0:
                return True

    # Check system python
    system_py = _find_system_python()
    p = _run([system_py, "-c", f"import {module}"])
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
        if os.name == "nt":
            py = d / "Scripts" / "python.exe"
        else:
            py = d / "bin" / "python"
        if py.exists():
            return py
    return None

def _venv_has_pylsp(repo: Path) -> bool:
    venv_dirs = [repo / ".venv", repo / "venv", _get_tools_venv(repo)]
    for d in venv_dirs:
        if os.name == "nt":
            pylsp = d / "Scripts" / "pylsp.exe"
        else:
            pylsp = d / "bin" / "pylsp"
        if pylsp.exists():
            return True
    return False

def _proxy_is_listening(port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False

def _proxy_pid_active(pid_file: Path) -> tuple[bool, int | None]:
    if not pid_file.exists():
        return False, None
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError):
        return False, None

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
                # Use repo venv
                p = _run([str(venv_py), "-m", "pip", "install", "python-lsp-server"])
                ok2 = (p.returncode == 0) and _venv_has_pylsp(repo)
                results.append(ToolStatus("pylsp", ok2, p.stderr.strip() or p.stdout.strip(), hint="Installed into venv"))
            else:
                system_py = _find_system_python()
                if _is_externally_managed_python(system_py):
                    # Create tools venv and install there
                    tools_py = _ensure_tools_venv(repo)
                    p = _run([tools_py, "-m", "pip", "install", "python-lsp-server"])
                    ok2 = (p.returncode == 0) and _venv_has_pylsp(repo)
                    results.append(ToolStatus("pylsp", ok2, p.stderr.strip() or p.stdout.strip(), hint="Installed into .ralph/tools-venv"))
                else:
                    # Use --user install
                    p = _run([system_py, "-m", "pip", "install", "--user", "python-lsp-server"])
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
        have_pw = _have_python_module("playwright", repo)
        if have_pw:
            results.append(ToolStatus("playwright-python", True, "python module found"))
        else:
            if install:
                system_py = _find_system_python()
                if _is_externally_managed_python(system_py):
                    # Create/use tools venv
                    tools_py = _ensure_tools_venv(repo)
                    p = _run([tools_py, "-m", "pip", "install", "playwright", "pytest-playwright"])
                    ok5 = p.returncode == 0 and _have_python_module("playwright", repo)
                    results.append(ToolStatus("playwright-python", ok5, p.stderr.strip() or p.stdout.strip(), hint="Installed into .ralph/tools-venv"))
                else:
                    p = _run([system_py, "-m", "pip", "install", "--user", "playwright", "pytest-playwright"])
                    ok5 = p.returncode == 0 and _have_python_module("playwright", repo)
                    results.append(ToolStatus("playwright-python", ok5, p.stderr.strip() or p.stdout.strip()))
            else:
                results.append(ToolStatus("playwright-python", False, "missing"))

        if install_playwright_browsers and install:
            # Use the python that has playwright installed
            tools_py = _get_tools_venv_python(repo)
            if tools_py:
                p = _run([tools_py, "-m", "playwright", "install", "chromium"])
            else:
                system_py = _find_system_python()
                p = _run([system_py, "-m", "playwright", "install", "chromium"])
            results.append(ToolStatus("playwright-browsers-chromium", p.returncode == 0, p.stderr.strip() or p.stdout.strip()))
    return results

def doctor_report(*, repo: Path, ollama_host: str, embed_model: str, vacuum_warn_mb: float = 200.0,
                  proxy_enabled: bool = False, proxy_listen_port: int = 18889) -> list[ToolStatus]:
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

    pw_found = _have_python_module("playwright", repo)
    statuses.append(ToolStatus("playwright-python", pw_found,
                               "found" if pw_found else "missing"))

    if proxy_enabled:
        pid_file = repo / ".ralph" / "proxy.pid"
        pid_active, pid = _proxy_pid_active(pid_file)
        port_listening = _proxy_is_listening(proxy_listen_port)

        if pid_active and port_listening:
            statuses.append(ToolStatus("proxy", True, f"running (PID {pid}) on port {proxy_listen_port}"))
        elif port_listening:
            statuses.append(ToolStatus("proxy", True, f"port {proxy_listen_port} in use (external process)"))
        else:
            statuses.append(ToolStatus("proxy", False, "not running",
                                       hint="Run: openralph proxy start ."))

    return statuses
