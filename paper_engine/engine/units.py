"""
units.py — unit-aware picking that keeps "intact" context blocks together.

Two context-block types are indivisible selection units, treated like passages:
    passage         reading-comprehension text + its sub-questions
    question_block  a shared table/graph/"main question" + its sub-questions

`direction` blocks are NOT intact — they are a shared instruction printed once
over up to ~140 questions, so selecting a subset is fine (they stay singles).

Picking within a chapter therefore works on UNITS: each intact block is one unit
(all its eligible sub-questions), every other question is a unit of size 1. We
add whole units until the target is reached, trimming only the last intact unit
if it would overshoot (same rule as passages). When a chapter has no intact
blocks at all, we delegate to the normal per-question modes.pick — so ordinary
chapters behave exactly as before (including stratified_by_type).
"""
from . import modes

INTACT_TYPES = {"passage", "question_block"}


def _is_intact(r):
    return r.get("cb_type") in INTACT_TYPES and r.get("context_block_id") is not None


def _rank_units(units, mode, usage, rng):
    """units: list of lists-of-rows. Orders whole units by the active mode."""
    if mode == "random":
        u = units[:]
        rng.shuffle(u)
        return u
    if mode == "sequential":
        return sorted(units, key=lambda u: min((r.get("question_number") or 0) for r in u))
    if mode == "pyq_recency":
        def key(u):
            yrs = [r.get("pyq_year") for r in u if isinstance(r.get("pyq_year"), int)]
            return (-(max(yrs) if yrs else -1), rng.random())
        return sorted(units, key=key)
    # repetition_least (and the fallback for stratified, which has no clean
    # per-unit type when a unit spans a whole block): least aggregate use first.
    def key(u):
        counts = [usage.get(r["id"], (0, ""))[0] for r in u]
        lasts = [usage.get(r["id"], (0, ""))[1] for r in u]
        return (sum(counts), max(lasts) if lasts else "", rng.random())
    return sorted(units, key=key)


def pick(mode, cands, n, usage, rng, strategy="redistribute"):
    """Return chosen question ids, keeping intact blocks together (trim last)."""
    if n <= 0 or not cands:
        return []
    if not any(_is_intact(r) for r in cands):
        # no passage/question_block here -> ordinary per-question selection
        return modes.pick(mode, cands, n, usage, rng, strategy)

    blocks = {}
    singles = []
    for r in cands:
        if _is_intact(r):
            blocks.setdefault(r["context_block_id"], []).append(r)
        else:
            singles.append(r)
    for rows in blocks.values():
        rows.sort(key=lambda r: (r.get("question_number") or 0, r["id"]))

    units = list(blocks.values()) + [[s] for s in singles]
    ranked = _rank_units(units, mode, usage, rng)

    chosen = []
    total = 0
    for u in ranked:
        if total >= n:
            break
        remaining = n - total
        take = u if len(u) <= remaining else u[:remaining]  # trim last intact block
        chosen.extend(take)
        total += len(take)
    return [r["id"] for r in chosen]
