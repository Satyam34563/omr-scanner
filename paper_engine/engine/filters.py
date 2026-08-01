"""
filters.py — turn a selection filter spec into a reusable SQL WHERE clause.

Every metadata query (for the cascading Laravel dropdowns) and the actual
selection share this one predicate builder, so what the UI *counts* as available
is exactly what selection is *allowed* to pick. Single source of truth.

The filters map directly onto columns of the `questions` table:
    language    -> questions.language          (exactly one, e.g. 'hindi')
    section_ids -> chapters.section_id          (via chapter join)
    chapter_ids -> questions.chapter_id
    types       -> questions.type
    pyq_only    -> questions.is_pyq = 1
    pyq_years   -> questions.pyq_year IN (...)   (only meaningful with pyq_only)
    pyq_exams   -> questions.pyq_exam IN (...)
    exclude_ids -> questions.id NOT IN (...)     (hard exclusion list)
"""
from __future__ import annotations  # keep annotations lazy for Python 3.9

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FilterSpec:
    language: Optional[str] = None
    section_ids: list[int] = field(default_factory=list)
    chapter_ids: list[int] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    pyq_only: bool = False
    pyq_years: list[int] = field(default_factory=list)
    pyq_exams: list[str] = field(default_factory=list)
    exclude_ids: list[int] = field(default_factory=list)


def _in_clause(column: str, values: list, params: list) -> str:
    placeholders = ",".join("?" for _ in values)
    params.extend(values)
    return f"{column} IN ({placeholders})"


def build_where(spec: FilterSpec, q_alias: str = "q", need_chapter_join: bool = False):
    """
    Returns (where_sql, params, join_sql).

    join_sql is a JOIN onto chapters when section filtering is requested (or
    when the caller explicitly needs chapter columns). where_sql always starts
    with a truthy '1=1' so callers can append ' AND ...' freely.
    """
    where = ["1=1"]
    params: list = []
    join_sql = ""

    if spec.language:
        where.append(f"{q_alias}.language = ?")
        params.append(spec.language)

    if spec.section_ids:
        join_sql = f" JOIN chapters c ON {q_alias}.chapter_id = c.id"
        where.append(_in_clause("c.section_id", spec.section_ids, params))
    elif need_chapter_join:
        join_sql = f" JOIN chapters c ON {q_alias}.chapter_id = c.id"

    if spec.chapter_ids:
        where.append(_in_clause(f"{q_alias}.chapter_id", spec.chapter_ids, params))

    if spec.types:
        where.append(_in_clause(f"{q_alias}.type", spec.types, params))

    if spec.pyq_only:
        where.append(f"{q_alias}.is_pyq = 1")
        if spec.pyq_years:
            where.append(_in_clause(f"{q_alias}.pyq_year", spec.pyq_years, params))
        if spec.pyq_exams:
            where.append(_in_clause(f"{q_alias}.pyq_exam", spec.pyq_exams, params))

    if spec.exclude_ids:
        placeholders = ",".join("?" for _ in spec.exclude_ids)
        params.extend(spec.exclude_ids)
        where.append(f"{q_alias}.id NOT IN ({placeholders})")

    return " AND ".join(where), params, join_sql
