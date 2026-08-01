"""
passages.py — passage-aware selection for language (reading-comprehension) sections.

UNIVERSAL RULE: a passage (context_block) is an indivisible unit — when a passage
is chosen, ALL its sub-questions come along. Because passages have fixed sizes
(often 5, but 1..138 in this DB), whole passages rarely sum to the exact target
the user asked for. So:

    fill with WHOLE passages while another whole passage still fits, then add ONE
    trimmed passage containing only as many sub-questions as needed to hit the
    target exactly.

e.g. target 23 with size-5 passages -> 4 whole passages (20) + 1 passage trimmed
to 3 = 23. The trimmed passage keeps its reading text; only its sub-question
count is reduced (first N in reading order).
"""
from . import db, fetch
from .filters import build_where


def is_passage_section(qcon, spec) -> bool:
    """True when every eligible question in this section belongs to a passage."""
    where, params, join = build_where(spec)
    row = db.one(
        qcon,
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN q.context_block_id IS NOT NULL THEN 1 ELSE 0 END) AS with_cb "
        f"FROM questions q{join} WHERE {where}",
        params,
    )
    return bool(row and row["total"] > 0 and row["total"] == row["with_cb"])


def _eligible_passages(qcon, spec):
    """Group eligible questions by context_block, preserving per-question meta.

    Returns list of dicts: {cb, qids:[...], years:[...], cname, cnum} in DB order.
    """
    where, params, join = build_where(spec)
    rows = db.dicts(
        qcon,
        f"SELECT q.context_block_id AS cb, q.id AS id, q.question_number AS qn, "
        f"q.pyq_year AS yr, c.name AS cname, c.chapter_number AS cnum "
        f"FROM questions q{join} "
        f"WHERE {where} AND q.context_block_id IS NOT NULL "
        f"ORDER BY q.context_block_id, q.question_number",
        params,
    )
    passages = {}
    order = []
    for r in rows:
        cb = r["cb"]
        if cb not in passages:
            passages[cb] = {"cb": cb, "qids": [], "years": [], "cname": r["cname"], "cnum": r["cnum"]}
            order.append(cb)
        passages[cb]["qids"].append(r["id"])
        passages[cb]["years"].append(r["yr"])
    return [passages[cb] for cb in order]


def _rank_passages(passages, mode, usage, rng):
    """Order passages by the active selection mode."""
    if mode == "random":
        ps = passages[:]
        rng.shuffle(ps)
        return ps
    if mode == "sequential":
        return passages[:]  # already in context_block / question order
    if mode == "pyq_recency":
        def key(p):
            yrs = [y for y in p["years"] if isinstance(y, int)]
            return (-(max(yrs) if yrs else -1), rng.random())
        return sorted(passages, key=key)
    # repetition_least (also the fallback for stratified_by_type, which has no
    # meaningful per-passage type): least aggregate usage first, then oldest.
    def key(p):
        counts = [usage.get(q, (0, ""))[0] for q in p["qids"]]
        lasts = [usage.get(q, (0, ""))[1] for q in p["qids"]]
        return (sum(counts), max(lasts) if lasts else "", rng.random())
    return sorted(passages, key=key)


def select_passage_section(qcon, spec, target, mode, usage, rng):
    """
    Returns (questions, warnings). `questions` are fully-hydrated question dicts
    in reading order (grouped by passage, passages in selection order), each
    tagged with _chapter_name/_chapter_number/_passage_id/_passage_order.
    """
    warnings = []
    passages = _eligible_passages(qcon, spec)
    if not passages:
        return [], ["passage section: no eligible passages found."]
    if not target or target <= 0:
        return [], warnings

    ranked = _rank_passages(passages, mode, usage, rng)

    chosen = []          # list of (qid, passage_order, cname, cnum, cb)
    total = 0
    order = 0
    for p in ranked:
        if total >= target:
            break
        remaining = target - total
        size = len(p["qids"])
        take = p["qids"] if size <= remaining else p["qids"][:remaining]  # trim last passage
        for qid in take:
            chosen.append((qid, order, p["cname"], p["cnum"], p["cb"]))
        total += len(take)
        order += 1

    if total < target:
        warnings.append(
            f"passage section: only {total} question(s) available across passages "
            f"(target {target}); short by {target - total}."
        )

    questions = []
    for qid, porder, cname, cnum, cb in chosen:
        q = fetch.fetch_full_question(qcon, qid)
        q["_chapter_name"] = cname
        q["_chapter_number"] = cnum
        q["_passage_id"] = cb
        q["_passage_order"] = porder
        questions.append(q)

    return questions, warnings
