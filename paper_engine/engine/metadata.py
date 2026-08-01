"""
metadata.py — cascading, post-filter counts that drive the Laravel dropdowns.

Every function returns options WITH their available count *after applying the
rest of the filter spec*, so the UI can never let the user request 20 questions
from a pool that only has 12. Each lister clears its own dimension from the spec
(e.g. listing sections ignores any section selection) so the counts reflect
"what's available if you pick this".
"""
import dataclasses

from . import db
from .filters import FilterSpec, build_where


def languages(con) -> list[dict]:
    return db.dicts(
        con,
        "SELECT language, COUNT(*) AS count FROM questions "
        "WHERE language IS NOT NULL GROUP BY language ORDER BY language",
    )


def sections(con, spec: FilterSpec) -> list[dict]:
    s = dataclasses.replace(spec, section_ids=[], chapter_ids=[])
    where, params, _ = build_where(s, need_chapter_join=True)
    return db.dicts(
        con,
        f"""
        SELECT sec.id, sec.name, COUNT(*) AS count
        FROM questions q
        JOIN chapters c ON q.chapter_id = c.id
        JOIN sections sec ON c.section_id = sec.id
        WHERE {where}
        GROUP BY sec.id, sec.name
        ORDER BY sec.id
        """,
        params,
    )


def chapters(con, spec: FilterSpec) -> list[dict]:
    s = dataclasses.replace(spec, chapter_ids=[])
    where, params, join = build_where(s, need_chapter_join=True)
    return db.dicts(
        con,
        f"""
        SELECT c.id, c.name, c.chapter_number, c.section_id, COUNT(*) AS count
        FROM questions q{join}
        WHERE {where}
        GROUP BY c.id, c.name, c.chapter_number, c.section_id
        ORDER BY c.section_id, c.chapter_number
        """,
        params,
    )


def types(con, spec: FilterSpec) -> list[dict]:
    s = dataclasses.replace(spec, types=[])
    where, params, join = build_where(s)
    return db.dicts(
        con,
        f"SELECT q.type, COUNT(*) AS count FROM questions q{join} "
        f"WHERE {where} AND q.type IS NOT NULL GROUP BY q.type ORDER BY count DESC",
        params,
    )


def pyq_exams(con, spec: FilterSpec) -> list[dict]:
    s = dataclasses.replace(spec, pyq_only=True, pyq_exams=[], pyq_years=[])
    where, params, join = build_where(s)
    return db.dicts(
        con,
        f"SELECT q.pyq_exam, COUNT(*) AS count FROM questions q{join} "
        f"WHERE {where} AND q.pyq_exam IS NOT NULL GROUP BY q.pyq_exam ORDER BY count DESC",
        params,
    )


def pyq_years(con, spec: FilterSpec) -> list[dict]:
    s = dataclasses.replace(spec, pyq_only=True, pyq_years=[])
    where, params, join = build_where(s)
    return db.dicts(
        con,
        f"SELECT q.pyq_year, COUNT(*) AS count FROM questions q{join} "
        f"WHERE {where} AND q.pyq_year IS NOT NULL GROUP BY q.pyq_year ORDER BY q.pyq_year DESC",
        params,
    )


def pool_size(con, spec: FilterSpec) -> int:
    """Total eligible questions for the full spec (used to validate totals)."""
    where, params, join = build_where(spec)
    row = db.one(con, f"SELECT COUNT(*) AS n FROM questions q{join} WHERE {where}", params)
    return row["n"] if row else 0
