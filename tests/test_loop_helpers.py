from __future__ import annotations

import sqlite3
from pathlib import Path

from openralph.openralph_cli import loop
from openralph.openralph_cli.memory.db import init_db


def test_parse_gate_pass() -> None:
    assert loop._parse_gate("Gate: PASS") is True
    assert loop._parse_gate("gate: pass") is True


def test_parse_gate_fail() -> None:
    assert loop._parse_gate("Gate: FAIL") is False
    assert loop._parse_gate("Gate: fail") is False


def test_parse_gate_missing() -> None:
    assert loop._parse_gate("No gate here") is None


def test_extract_json_from_response() -> None:
    payload = '{"project_name": "Ralph", "problem": "X"}'
    assert loop._extract_json_from_response(payload) == {
        "project_name": "Ralph",
        "problem": "X",
    }
    assert loop._extract_json_from_response("not json") is None


def test_memory_chunk_count_missing_db() -> None:
    assert loop._memory_chunk_count(Path("/tmp/does-not-exist-memory.sqlite3")) == 0


def test_memory_chunk_count_reads_chunks(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite3"
    init_db(db_path)

    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            INSERT INTO chunks (
              doc_id, path, chunk_index, content, content_hash, start_offset, end_offset,
              embedding, dim, updated_at, last_seen_scan
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1",
                "a.py",
                0,
                "print('x')",
                "hash",
                0,
                10,
                sqlite3.Binary(b"\x00\x00\x00\x00"),
                1,
                "2026-02-07T00:00:00+00:00",
                "scan-1",
            ),
        )
        con.commit()
    finally:
        con.close()

    assert loop._memory_chunk_count(db_path) == 1
