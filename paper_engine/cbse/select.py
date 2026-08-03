"""
select.py — CBSE blueprint selection from questionsitoviii.db.

Per bucket (type + marks): distribute the count ACROSS chapters (equal split or
an explicit per-chapter map), pick within each chapter by the selection mode
(random / sequential / repetition_least), redistribute on shortfall, and record
usage — the same machinery the competitive selector uses. Case-based buckets
pick whole context blocks (case studies), also distributed across chapters.
"""
from __future__ import annotations

import random

from engine import db as _db
from engine.alloc import equal_allocate
from . import blueprint as _bp

LETTERS = ["a", "b", "c", "d", "e", "f"]


# --------------------------------------------------------------- metadata
def book_for_class(con, class_number, subject=None):
    q, p = "SELECT * FROM books WHERE class_number=?", [class_number]
    if subject:
        q += " AND subject=?"
        p.append(subject)
    return _db.one(con, q + " LIMIT 1", p)


def chapters_for_book(con, book_id):
    return _db.dicts(con, "SELECT id, name, chapter_number FROM chapters WHERE book_id=? ORDER BY chapter_number", (book_id,))


# --------------------------------------------------------------- candidates
def _candidates(con, book_id, types, marks, chapter_ids, difficulties, intact):
    where = ["q.chapter_id IN (SELECT id FROM chapters WHERE book_id=?)"]
    params = [book_id]
    where.append("q.type IN (%s)" % ",".join("?" for _ in types)); params += list(types)
    if not intact and marks is not None:
        where.append("q.marks = ?"); params.append(float(marks))
    if chapter_ids:
        where.append("q.chapter_id IN (%s)" % ",".join("?" for _ in chapter_ids)); params += list(chapter_ids)
    if difficulties:
        where.append("q.difficulty IN (%s)" % ",".join("?" for _ in difficulties)); params += list(difficulties)
    if intact:
        where.append("q.context_block_id IS NOT NULL")
    return _db.dicts(
        con,
        f"SELECT q.id, q.question_number, q.chapter_id, q.context_block_id FROM questions q WHERE {' AND '.join(where)}",
        params,
    )


def fetch_full_question(con, qid):
    q = _db.one(con, "SELECT * FROM questions WHERE id=?", (qid,))
    opts = _db.dicts(con, "SELECT label, text, text_latex, image FROM options WHERE question_id=? ORDER BY label", (qid,))
    orig_correct = (q.get("correct_answer_latex") or q.get("correct_answer") or "").strip().lower()
    new_correct = None
    for i, opt in enumerate(opts):
        orig = (opt.get("label") or "").strip().lower()
        new = LETTERS[i] if i < len(LETTERS) else opt["label"]
        if orig and orig == orig_correct:
            new_correct = new
        opt["label"] = new
    q["options"] = opts
    q["correct_answer_display"] = new_correct or q.get("correct_answer_latex") or q.get("correct_answer")
    return q


# --------------------------------------------------------------- modes
def _pick(mode, rows, n, usage, rng):
    if n <= 0 or not rows:
        return []
    if n >= len(rows):
        return [r["id"] for r in rows]
    if mode == "sequential":
        return [r["id"] for r in sorted(rows, key=lambda r: (r.get("question_number") or 0, r["id"]))[:n]]
    if mode == "repetition_least":
        def key(r):
            uc, last = usage.get(r["id"], (0, ""))
            return (uc, last or "", rng.random())
        return [r["id"] for r in sorted(rows, key=key)[:n]]
    return [r["id"] for r in rng.sample(rows, n)]  # random


def _rank_blocks(block_items, mode, usage, rng):
    """block_items: [(cb_id, [rows])] -> ordered by mode."""
    if mode == "sequential":
        return sorted(block_items, key=lambda t: min((r.get("question_number") or 0) for r in t[1]))
    if mode == "repetition_least":
        def key(t):
            counts = [usage.get(r["id"], (0, ""))[0] for r in t[1]]
            return (sum(counts), rng.random())
        return sorted(block_items, key=key)
    b = block_items[:]
    rng.shuffle(b)
    return b


# --------------------------------------------------------------- main
def select_paper(con, cfg, usage_map=None):
    usage_map = usage_map or {}
    rng = random.Random(cfg.get("random_seed"))
    mode = cfg.get("selection_mode", "random")
    strategy = cfg.get("shortfall_strategy", "redistribute")
    warnings = []
    chosen_ids = []

    class_number = cfg["class_number"]
    book = book_for_class(con, class_number, cfg.get("subject"))
    if not book:
        raise ValueError(f"no book for class {class_number}")
    chapter_ids = [int(x) for x in (cfg.get("chapters") or [])]
    difficulties = list(cfg.get("difficulty") or [])
    chmap = {c["id"]: c["name"] for c in chapters_for_book(con, book["id"])}

    sections_out = []
    blocks = {}

    for bk in _bp.resolve_buckets(cfg):
        rows = _candidates(con, book["id"], bk["types"], bk.get("marks"), chapter_ids, difficulties, bk["intact"])
        q_ids_ordered = []  # (qid, sort_key) preserving chapter grouping

        if bk["intact"]:
            # group rows -> chapter -> case block -> rows; distribute CASES across chapters
            by_ch = {}
            for r in rows:
                by_ch.setdefault(r["chapter_id"], {}).setdefault(r["context_block_id"], []).append(r)
            caps = {cid: len(bl) for cid, bl in by_ch.items()}
            take, w = _resolve_take(bk, caps, rng, strategy)
            warnings += [f"[{bk['key']}] {m}" for m in w]
            order = 0
            for cid, k in take.items():
                ranked = _rank_blocks(list(by_ch[cid].items()), mode, usage_map, rng)
                for cb_id, brows in ranked[:k]:
                    cb = _db.one(con, "SELECT * FROM context_blocks WHERE id=?", (cb_id,))
                    if cb:
                        blocks[str(cb_id)] = {kk: cb.get(kk) for kk in ("id", "type", "category", "text", "text_latex", "image")}
                    for r in sorted(brows, key=lambda x: (x.get("question_number") or 0, x["id"])):
                        q_ids_ordered.append((r["id"], (cid, order, r.get("question_number") or 0)))
                    order += 1
        else:
            by_ch = {}
            for r in rows:
                by_ch.setdefault(r["chapter_id"], []).append(r)
            caps = {cid: len(v) for cid, v in by_ch.items()}
            take, w = _resolve_take(bk, caps, rng, strategy)
            warnings += [f"[{bk['key']}] {m}" for m in w]
            for cid, k in take.items():
                for qid in _pick(mode, by_ch[cid], k, usage_map, rng):
                    q_ids_ordered.append((qid, (cid, 0, 0)))

        q_ids_ordered.sort(key=lambda t: t[1])  # keep chapter order tidy
        questions = []
        for qid, _k in q_ids_ordered:
            q = fetch_full_question(con, qid)
            q["section_marks"] = None if bk["intact"] else bk["marks"]
            q["_chapter_name"] = chmap.get(q.get("chapter_id"))
            questions.append(q)
            chosen_ids.append(qid)

        sections_out.append({
            "code": bk["code"], "title": bk["title"], "instruction": bk["instruction"],
            "marks_per": bk["marks"], "intact_blocks": bk["intact"], "questions": questions,
        })

    # continuous display numbering
    n = 1
    for sec in sections_out:
        for q in sec["questions"]:
            q["display_number"] = n
            n += 1

    max_marks = 0
    for sec in sections_out:
        if sec["intact_blocks"]:
            max_marks += sec["marks_per"] * len({q.get("context_block_id") for q in sec["questions"] if q.get("context_block_id")})
        else:
            max_marks += sec["marks_per"] * len(sec["questions"])

    content = {
        "exam_type": "cbse",
        "paper_title": cfg.get("paper_title", f"{book.get('subject','')} — Class {book.get('class_level','')}"),
        "class_label": book.get("class_level"), "class_number": class_number,
        "subject": book.get("subject"), "book_title": book.get("title"),
        "exam_duration": cfg.get("exam_duration", "3 Hours"),
        "max_marks": round(max_marks, 1),
        "two_column": bool(cfg.get("two_column", False)),
        "sections": sections_out, "context_blocks": blocks, "warnings": warnings,
    }
    return content, chosen_ids


def _resolve_take(bucket, caps, rng, strategy):
    """Per-chapter counts for a bucket: explicit map (validated) or equal split."""
    if bucket.get("chapters"):
        take, warns = {}, []
        for cid, want in bucket["chapters"].items():
            avail = caps.get(cid, 0)
            got = min(want, avail)
            if got < want:
                warns.append(f"chapter {cid} wanted {want}, only {got} available.")
            if got > 0:
                take[cid] = got
        return take, warns
    return equal_allocate(bucket["count"], caps, rng, strategy)
