"""
db.py — read-only access to the live questions.db.

IMPORTANT: questions.db is written by a separate ingestion pipeline while this
engine runs. We open it strictly read-only (mode=ro) and with a busy timeout so
a concurrent writer never causes a hard "database is locked" failure. The engine
NEVER writes to questions.db — usage history lives in a separate sidecar DB
(see usage.py / schema.py).
"""
import sqlite3
from pathlib import Path


def connect_questions(db_path: str) -> sqlite3.Connection:
    """Open questions.db read-only. Raises FileNotFoundError if missing."""
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"questions.db not found at: {db_path}")
    # file: URI with mode=ro guarantees we can never write to the live DB.
    uri = f"file:{p.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30.0)
    con.row_factory = sqlite3.Row
    # Wait up to 30s if the ingestion pipeline holds a lock, instead of erroring.
    con.execute("PRAGMA busy_timeout = 30000")
    return con


def rows(con: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    return con.execute(sql, params).fetchall()


def dicts(con: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(con: sqlite3.Connection, sql: str, params=()):
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None
