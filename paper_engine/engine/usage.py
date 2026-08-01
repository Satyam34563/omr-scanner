"""
usage.py — the sidecar usage-history DB that powers repetition-least selection.

Lives in a SEPARATE file (paper_usage.db), never in questions.db, because the
live questions.db is being written by the ingestion pipeline and we must not add
write contention there. This DB is small and fully owned by the engine.

    usage_history(question_id, paper_name, used_at)

use_count / last_used per question are derived on demand. Recorded once per
generated paper, for every question that made it onto the paper.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS usage_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL,
    paper_name   TEXT,
    used_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_qid ON usage_history(question_id);
"""


def connect_usage(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(DDL)
    con.commit()
    return con


def usage_map(con: sqlite3.Connection) -> dict[int, tuple[int, str]]:
    """question_id -> (use_count, last_used_at). Absent = never used."""
    out = {}
    for r in con.execute(
        "SELECT question_id, COUNT(*) AS n, MAX(used_at) AS last "
        "FROM usage_history GROUP BY question_id"
    ):
        out[r["question_id"]] = (r["n"], r["last"])
    return out


def record(con: sqlite3.Connection, question_ids, paper_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con.executemany(
        "INSERT INTO usage_history(question_id, paper_name, used_at) VALUES (?,?,?)",
        [(qid, paper_name, now) for qid in question_ids],
    )
    con.commit()
