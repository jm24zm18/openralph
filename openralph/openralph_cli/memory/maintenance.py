from __future__ import annotations
from pathlib import Path
import sqlite3

def vacuum_db(db_path: Path) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Memory DB not found: {db_path}")
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        con.execute("ANALYZE;")
        con.execute("VACUUM;")
        con.commit()
    finally:
        con.close()
