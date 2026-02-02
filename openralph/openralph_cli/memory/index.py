from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib, sqlite3, struct
from datetime import datetime, timezone
from typing import Iterable, List, Tuple

from .embed import ollama_embed

DEFAULT_INCLUDE_EXTS = {
    ".md", ".mdx", ".markdown", ".txt",
    ".py",
    ".js", ".ts", ".jsx", ".tsx",
    ".html", ".htm",
    ".css", ".scss", ".less",
    ".json", ".jsonc", ".yaml", ".yml", ".toml"
}
DEFAULT_EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph"}

@dataclass(frozen=True)
class Chunk:
    doc_id: str
    path: str
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def pack_f32(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)

def chunk_text(text: str, max_chars: int, overlap: int) -> List[Tuple[int,int,str]]:
    out: List[Tuple[int,int,str]] = []
    n = len(text)
    if n == 0:
        return out
    i = 0
    while i < n:
        j = min(n, i + max_chars)
        out.append((i, j, text[i:j]))
        if j == n:
            break
        i = max(0, j - overlap)
    return out

def iter_files(root: Path, include_exts: set[str], exclude_dirs: set[str]) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in exclude_dirs for part in rel_parts):
            continue
        if p.suffix.lower() in include_exts:
            yield p

def upsert_chunk(con: sqlite3.Connection, c: Chunk, emb: List[float], scan_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    dim = len(emb)
    blob = pack_f32(emb)
    h = sha256(c.content)
    con.execute("""
    INSERT INTO chunks (
      doc_id, path, chunk_index, content, content_hash, start_offset, end_offset,
      embedding, dim, updated_at, last_seen_scan
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(doc_id, chunk_index) DO UPDATE SET
      path=excluded.path,
      content=excluded.content,
      content_hash=excluded.content_hash,
      start_offset=excluded.start_offset,
      end_offset=excluded.end_offset,
      embedding=excluded.embedding,
      dim=excluded.dim,
      updated_at=excluded.updated_at,
      last_seen_scan=excluded.last_seen_scan
    """, (
        c.doc_id, c.path, c.chunk_index, c.content, h, c.start_offset, c.end_offset,
        blob, dim, now, scan_id
    ))

def index_repo(
    repo: Path,
    db_path: Path,
    ollama_host: str,
    embed_model: str,
    batch: int = 6,
    include_exts: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
    chunk_chars: int = 1800,
    chunk_overlap: int = 200,
) -> None:
    include_exts = include_exts or DEFAULT_INCLUDE_EXTS
    exclude_dirs = exclude_dirs or DEFAULT_EXCLUDE_DIRS

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")

    root = repo.resolve()
    repo_name = root.name
    scan_id = datetime.now(timezone.utc).isoformat()

    for fp in iter_files(root, include_exts, exclude_dirs):
        rel = fp.relative_to(root).as_posix()
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        doc_id = sha256(f"{repo_name}:{rel}")
        parts = chunk_text(text, max_chars=chunk_chars, overlap=chunk_overlap)
        chunks = [Chunk(doc_id, rel, idx, chunk, a, b) for idx, (a, b, chunk) in enumerate(parts)]

        # mark doc seen
        con.execute("UPDATE chunks SET last_seen_scan=? WHERE doc_id=?", (scan_id, doc_id))

        changed: list[Chunk] = []
        for c in chunks:
            row = con.execute(
                "SELECT content_hash FROM chunks WHERE doc_id=? AND chunk_index=?",
                (c.doc_id, c.chunk_index),
            ).fetchone()
            if not row or row[0] != sha256(c.content):
                changed.append(c)

        for i in range(0, len(changed), batch):
            for c in changed[i:i + batch]:
                emb = ollama_embed(ollama_host, embed_model, c.content)
                upsert_chunk(con, c, emb, scan_id)
            con.commit()

        con.execute("DELETE FROM chunks WHERE doc_id=? AND chunk_index>=?", (doc_id, len(chunks)))
        con.commit()

    # stale cleanup
    con.execute("DELETE FROM chunks WHERE last_seen_scan != ?", (scan_id,))
    con.commit()
    con.close()
