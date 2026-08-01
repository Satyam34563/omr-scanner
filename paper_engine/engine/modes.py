"""
modes.py — the five selection strategies. Each decides WHICH question ids to
pick from a chapter's eligible candidate pool. Final display order is set later
by the selector (chapter_number, question_number), so a mode only chooses the
SET of ids, not their printed order.

candidate rows are dicts with: id, question_number, type, pyq_year
usage is {qid -> (use_count, last_used_at)} from usage.py (absent = never used).
"""
from .alloc import equal_allocate


def _rank_repetition_least(cands, usage, rng):
    """Never-used first, then oldest-used, then random tiebreak."""
    decorated = []
    for c in cands:
        uc, last = usage.get(c["id"], (0, ""))
        decorated.append(((uc, last or "", rng.random()), c))
    decorated.sort(key=lambda t: t[0])
    return [c for _, c in decorated]


def _rank_pyq_recency(cands, usage, rng):
    """Most recent pyq_year first; ties broken by repetition-least."""
    def key(c):
        year = c.get("pyq_year")
        # higher year first => negate; missing year sorts last
        year_key = -(year if isinstance(year, int) else -10**9)
        uc, last = usage.get(c["id"], (0, ""))
        return (year_key, uc, last or "", rng.random())
    return sorted(cands, key=key)


def pick(mode, cands, n, usage, rng, strategy="redistribute"):
    """Return a list of chosen question ids (length <= n)."""
    if n <= 0 or not cands:
        return []
    if n >= len(cands):
        return [c["id"] for c in cands]

    if mode == "random":
        return [c["id"] for c in rng.sample(cands, n)]

    if mode == "sequential":
        ordered = sorted(cands, key=lambda c: (c.get("question_number") or 0, c["id"]))
        return [c["id"] for c in ordered[:n]]

    if mode == "repetition_least":
        return [c["id"] for c in _rank_repetition_least(cands, usage, rng)[:n]]

    if mode == "pyq_recency":
        return [c["id"] for c in _rank_pyq_recency(cands, usage, rng)[:n]]

    if mode == "stratified_by_type":
        # split n across the types present, as evenly as capacity allows, then
        # pick within each type by repetition-least (fresh + type-balanced).
        by_type = {}
        for c in cands:
            by_type.setdefault(c.get("type") or "unknown", []).append(c)
        capacity = {t: len(v) for t, v in by_type.items()}
        take, _ = equal_allocate(n, capacity, rng, strategy)
        chosen = []
        for t, k in take.items():
            ranked = _rank_repetition_least(by_type[t], usage, rng)
            chosen.extend(c["id"] for c in ranked[:k])
        return chosen

    raise ValueError(f"unknown selection_mode: {mode}")
