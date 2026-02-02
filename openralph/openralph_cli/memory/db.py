from __future__ import annotations
from pathlib import Path
import sqlite3

def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
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
    """)
    con.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_unique
    ON chunks(doc_id, chunk_index);
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_last_seen ON chunks(last_seen_scan);")
    con.commit()
    con.close()
