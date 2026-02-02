from __future__ import annotations

import os
import platform
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen, Request
import subprocess

REPO = "anomalyco/opencode"
APP = "opencode"

@dataclass(frozen=True)
class OpenCodeInstallResult:
    path: Path
    source: str  # bundled|path

def opencode_bundle_path(repo: Path) -> Path:
    exe = "opencode.exe" if os.name == "nt" else "opencode"
    return repo.resolve() / ".ralph" / "bin" / exe

def find_opencode(repo: Path) -> OpenCodeInstallResult | None:
    repo = repo.resolve()
    bundled = opencode_bundle_path(repo)
    if bundled.exists():
        return OpenCodeInstallResult(bundled, "bundled")
    sysbin = shutil.which("opencode")
    if sysbin:
        return OpenCodeInstallResult(Path(sysbin), "path")
    return None

def ensure_opencode(repo: Path, *, auto_install: bool, version: str = "") -> OpenCodeInstallResult:
    found = find_opencode(repo)
    if found is not None:
        return found
    if not auto_install:
        raise RuntimeError("OpenCode not found. Run: openralph opencode install")
    p = install_opencode(repo, version=version)
    return OpenCodeInstallResult(p, "bundled")

def install_opencode(repo: Path, *, version: str = "") -> Path:
    repo = repo.resolve()
    dest = opencode_bundle_path(repo)
    dest.parent.mkdir(parents=True, exist_ok=True)

    os_name = _detect_os()
    arch = _detect_arch()
    target = f"{os_name}-{arch}"

    if os_name == "linux":
        if _is_musl():
            target = f"{target}-musl"
        elif arch == "x64" and _needs_baseline_linux_x64():
            target = f"{target}-baseline"
    elif os_name == "darwin":
        if arch == "x64" and _needs_baseline_darwin_x64():
            target = f"{target}-baseline"

    ext = ".tar.gz" if os_name == "linux" else ".zip"
    filename = f"{APP}-{target}{ext}"

    if version:
        v = version.lstrip("v")
        url = f"https://github.com/{REPO}/releases/download/v{v}/{filename}"
    else:
        url = f"https://github.com/{REPO}/releases/latest/download/{filename}"

    with TemporaryDirectory(prefix="openralph_opencode_") as td:
        td_path = Path(td)
        archive = td_path / filename
        _download(url, archive)
        extracted = _extract_archive(archive, td_path, os_name=os_name)

        candidate = extracted / ("opencode.exe" if os_name == "windows" else "opencode")
        if not candidate.exists():
            candidate = _find_file(extracted, "opencode.exe" if os_name == "windows" else "opencode")
            if candidate is None:
                raise RuntimeError(f"Downloaded archive did not contain '{APP}' binary: {archive}")

        shutil.copy2(candidate, dest)
        _make_executable(dest)
        return dest

def opencode_version(opencode_path: Path) -> str:
    try:
        p = subprocess.run([str(opencode_path), "--version"], text=True, capture_output=True)
        out = (p.stdout or p.stderr).strip()
        return out if out else "unknown"
    except Exception:
        return "unknown"

def _detect_os() -> str:
    raw = platform.system().lower()
    if "darwin" in raw or "mac" in raw:
        return "darwin"
    if "linux" in raw:
        return "linux"
    if "windows" in raw or "msys" in raw or "mingw" in raw:
        return "windows"
    raise RuntimeError(f"Unsupported OS: {platform.system()}")

def _detect_arch() -> str:
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x64"
    raise RuntimeError(f"Unsupported arch: {platform.machine()}")

def _is_musl() -> bool:
    if Path("/etc/alpine-release").exists():
        return True
    ldd = shutil.which("ldd")
    if not ldd:
        return False
    try:
        p = subprocess.run([ldd, "--version"], text=True, capture_output=True)
        return "musl" in (p.stdout + p.stderr).lower()
    except Exception:
        return False

def _needs_baseline_linux_x64() -> bool:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
        return "avx2" not in text
    except Exception:
        return False

def _needs_baseline_darwin_x64() -> bool:
    try:
        p = subprocess.run(["sysctl", "-n", "hw.optional.avx2_0"], text=True, capture_output=True)
        val = (p.stdout or "").strip()
        return val != "1"
    except Exception:
        return False

def _download(url: str, out_path: Path) -> None:
    req = Request(url, headers={"User-Agent": "openralph/0.1"})
    with urlopen(req) as r:
        out_path.write_bytes(r.read())

def _extract_archive(archive: Path, into: Path, *, os_name: str) -> Path:
    out_dir = into / "extracted"
    out_dir.mkdir(parents=True, exist_ok=True)
    if os_name == "linux":
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(out_dir)
    else:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(out_dir)
    return out_dir

def _find_file(root: Path, name: str) -> Path | None:
    for p in root.rglob("*"):
        if p.is_file() and p.name == name:
            return p
    return None

def _make_executable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
