from __future__ import annotations

from pathlib import Path
from typing import Iterable
import re
import sqlite3

from ..paths import Paths
from ..prd import PRD_QA_QUESTIONS
from ..json_extract import extract_json_object


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:40] or "work"


def _read_text(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
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
    except ValueError:
        pass
    return str(path)


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


def _clear_human_exchange(request_path: Path, response_path: Path) -> None:
    if request_path.exists():
        request_path.unlink()
    if response_path.exists():
        response_path.unlink()


def _extract_json_from_response(text: str) -> dict[str, str] | None:
    data = extract_json_object(text)
    if not isinstance(data, dict):
        return None
    return data


def _validate_prd_answers(data: dict[str, str] | None) -> bool:
    if not data or not isinstance(data, dict):
        return False
    expected_keys = {key for key, _ in PRD_QA_QUESTIONS}
    if not expected_keys.issubset(set(data.keys())):
        return False
    for key in expected_keys:
        value = data.get(key)
        if not isinstance(value, str):
            return False
    return True


def _clear_prd_handoff_if_present(paths: Paths) -> None:
    if not paths.human_request.exists():
        return
    content = _read_text(paths.human_request, max_chars=2000)
    if "# PRD Q&A" in content:
        _clear_human_exchange(paths.human_request, paths.human_response)


def _memory_chunk_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()
