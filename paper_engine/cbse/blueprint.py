"""
blueprint.py — the CBSE paper blueprint.

A blueprint is an ordered list of BUCKETS. Each bucket selects questions of a
given `type` + `marks`, and its `count` is distributed ACROSS chapters (equal
split, or an explicit per-chapter map). Buckets are grouped into printed
sections by `code` ("A".."E").

  key       unique id used for config overrides — always f"{type}_{marks}"
            (e.g. "mcq_1", "short_answer_3"), except intact types which get
            ONE bucket keyed by `type` alone (see below)
  code      printed section letter (buckets sharing a code print under one heading)
  title     section heading (blank => continues the previous section)
  instruction  the line under the heading
  types     DB question `type`s this bucket pulls from
  marks     marks per question (also the source-marks filter; None for case blocks)
  count     how many questions (for intact buckets: how many CASE BLOCKS)
  intact    True => whole context_blocks (case studies), sub-questions kept together
  chapters  optional {chapter_id: count} explicit split; None => equal split

Buckets are DISCOVERED, not assumed: for the books being drawn from, every
(type, marks) combination actually present among ACTIVE questions gets its own
bucket. Nothing about the marks scheme is hardcoded here (a `type` is never
assumed to only ever carry one particular marks value, e.g. "MCQs are always
1 mark" or "Assertion–Reason is always 1 mark") — a chapter/subject with an
unusual marks value for a type still gets a selectable bucket, and a subject
that never uses a given marks value doesn't grow an always-empty row for it.

TYPE_META below only declares the STRUCTURE: which printed section (A..E) a
`type` prints under, its heading wording, and whether it picks whole
context_blocks intact. `default_counts` restores the standard CBSE pattern's
usual count for the marks value that pattern actually uses (e.g. 16 one-mark
MCQs); any other (type, marks) combo starts at count 0 so it never inflates a
paper the admin didn't ask for.

Intact (case-based) types stay a SINGLE bucket regardless of how many marks
values are present: a case study routinely mixes sub-questions of different
marks within the SAME context_block_id (confirmed in the data — a block is
not "the 2-mark case blocks" vs "the 3-mark case blocks"), and cbse/select.py's
_candidates() never filters intact buckets by marks anyway. Splitting an
intact type by marks would just create several buckets all drawing from the
exact same block pool.
"""

TYPE_META = {
    "mcq":               {"code": "A", "label": "Multiple Choice Questions", "default_counts": {1: 16}},
    "assertion_reason":  {"code": "A", "label": "Assertion–Reason",          "default_counts": {2: 4}},
    "very_short_answer": {"code": "B", "label": "Very Short Answer",         "default_counts": {1: 5}},
    "short_answer":      {"code": "C", "label": "Short Answer",              "default_counts": {3: 6}},
    "long_answer":       {"code": "D", "label": "Long Answer",               "default_counts": {5: 4}},
    "case_based":        {"code": "E", "label": "Case-Based Questions",      "default_counts": {4: 3}, "intact": True},
}
# printed order: MCQ/AR share Section A, then B, C, D, E — the standard CBSE
# Class-VIII pattern this blueprint was modelled on.
TYPE_ORDER = ["mcq", "assertion_reason", "very_short_answer", "short_answer", "long_answer", "case_based"]


def _marks_slug(m):
    return str(int(m)) if float(m).is_integer() else str(m).replace(".", "p")


def _fmt_marks(m):
    n = int(m) if float(m).is_integer() else m
    return f"{n} mark" + ("" if n == 1 else "s")


def discover_buckets(con, book_ids):
    """Every selectable bucket for these books, built from what ACTIVE
    questions actually exist (see module docstring) rather than an assumed
    marks pattern."""
    from engine import db as _db
    if not book_ids:
        return []
    ph = ",".join("?" for _ in book_ids)
    rows = _db.dicts(
        con,
        "SELECT DISTINCT q.type, q.marks FROM questions q "
        f"WHERE q.chapter_id IN (SELECT id FROM chapters WHERE book_id IN ({ph})) AND q.is_active != 0",
        list(book_ids),
    )
    marks_by_type = {}
    for r in rows:
        marks_by_type.setdefault(r["type"], set()).add(r["marks"])

    buckets, seen_codes = [], set()

    def expand(t, marks_values, meta):
        code = meta["code"]
        for m in sorted(marks_values):
            first = code not in seen_codes
            seen_codes.add(code)
            buckets.append({
                "key": f"{t}_{_marks_slug(m)}", "code": code,
                "title": f"Section {code}" if first else "",
                "instruction": f"{meta['label']} — {_fmt_marks(m)} each.",
                "types": [t], "marks": float(m),
                "count": meta.get("default_counts", {}).get(m, 0),
                "intact": False,
            })

    for t in TYPE_ORDER:
        meta = TYPE_META[t]
        marks_values = marks_by_type.pop(t, None)
        if not marks_values:
            continue
        if meta.get("intact"):
            code = meta["code"]
            first = code not in seen_codes
            seen_codes.add(code)
            default_marks, default_count = next(iter(meta["default_counts"].items()))
            buckets.append({
                "key": t, "code": code, "title": f"Section {code}" if first else "",
                "instruction": f"{meta['label']} — {_fmt_marks(default_marks)} each.",
                "types": [t], "marks": float(default_marks), "count": default_count, "intact": True,
            })
        else:
            expand(t, marks_values, meta)

    # a `type` the data has that isn't part of the standard pattern still gets
    # a bucket of its own, appended after — never silently dropped.
    for t in sorted(marks_by_type):
        code = (t[:1] or "X").upper()
        expand(t, marks_by_type[t], {"code": code, "label": t.replace("_", " ").title()})

    return buckets


def resolve_buckets(con, book_ids, cfg):
    """
    Merge cfg['sections'] (a {key: {count?, marks?, chapters?}} map) onto the
    discovered buckets. A bucket with count 0 is dropped.
    """
    overrides = cfg.get("sections") or {}
    out = []
    for b in discover_buckets(con, book_ids):
        ov = overrides.get(b["key"]) or {}
        if "count" in ov:
            b["count"] = int(ov["count"])
        if "marks" in ov and ov["marks"] is not None:
            b["marks"] = float(ov["marks"])
        if "chapters" in ov and ov["chapters"]:
            b["chapters"] = {int(k): int(v) for k, v in ov["chapters"].items()}
        if b["count"] > 0:
            out.append(b)
    return out
