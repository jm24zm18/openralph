from __future__ import annotations

import struct
import sqlite3
from pathlib import Path

from openralph.openralph_cli.memory.query import _apply_path_boost, query_memory


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _setup_db(tmp_path: Path) -> Path:
    db = tmp_path / "memory.sqlite3"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          doc_id TEXT NOT NULL,
          path TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          content TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          start_offset INTEGER NOT NULL,
          end_offset INTEGER NOT NULL,
          embedding BLOB NOT NULL,
          dim INTEGER NOT NULL,
          updated_at TEXT NOT NULL,
          last_seen_scan TEXT NOT NULL DEFAULT ''
        );
        """
    )
    con.execute(
        """
        INSERT INTO chunks(doc_id, path, chunk_index, content, content_hash, start_offset, end_offset, embedding, dim, updated_at, last_seen_scan)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("doc1", "docs/PRD.md", 0, "prd", "hash", 0, 3, _pack([1.0, 0.0]), 2, "now", "scan"),
    )
    con.execute(
        """
        INSERT INTO chunks(doc_id, path, chunk_index, content, content_hash, start_offset, end_offset, embedding, dim, updated_at, last_seen_scan)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("doc2", "src/app.py", 0, "code", "hash", 0, 4, _pack([1.0, 0.0]), 2, "now", "scan"),
    )
    con.commit()
    con.close()
    return db


def test_apply_path_boost_prefix() -> None:
    boosted = _apply_path_boost("docs/PRD.md", 0.5, [("docs/PRD.md", 2.0)])
    assert boosted == 1.0


def test_query_memory_applies_boost(monkeypatch, tmp_path: Path) -> None:
    db = _setup_db(tmp_path)

    def _fake_embed(_host: str, _model: str, _text: str) -> list[float]:
        return [1.0, 0.0]

    monkeypatch.setattr("openralph.openralph_cli.memory.query.ollama_embed", _fake_embed)
    hits = query_memory(
        db,
        "http://localhost:11434",
        "model",
        "query",
        k=2,
        path_boosts=[("docs/PRD.md", 2.0)],
    )
    assert hits[0].path == "docs/PRD.md"
