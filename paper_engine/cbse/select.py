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
def books_for_class(con, class_number, subject=None):
    """ALL books for (class, subject) — a subject may span several books."""
    q, p = "SELECT * FROM books WHERE class_number=?", [class_number]
    if subject:
        q += " AND subject=?"
        p.append(subject)
    return _db.dicts(con, q + " ORDER BY id", p)


def book_for_class(con, class_number, subject=None):
    rows = books_for_class(con, class_number, subject)
    return rows[0] if rows else None


def chapters_for_books(con, book_ids):
    ph = ",".join("?" for _ in book_ids)
    return _db.dicts(
        con,
        f"SELECT id, name, chapter_number FROM chapters WHERE book_id IN ({ph}) ORDER BY book_id, chapter_number",
        list(book_ids))


# --------------------------------------------------------------- candidates
def _candidates(con, book_ids, types, marks, chapter_ids, difficulties, intact, paper_tags=None):
    ph = ",".join("?" for _ in book_ids)
    where = [f"q.chapter_id IN (SELECT id FROM chapters WHERE book_id IN ({ph}))"]
    params = list(book_ids)
    where.append("q.type IN (%s)" % ",".join("?" for _ in types)); params += list(types)
    if not intact and marks is not None:
        where.append("q.marks = ?"); params.append(float(marks))
    if chapter_ids:
        where.append("q.chapter_id IN (%s)" % ",".join("?" for _ in chapter_ids)); params += list(chapter_ids)
    if difficulties:
        where.append("q.difficulty IN (%s)" % ",".join("?" for _ in difficulties)); params += list(difficulties)
    # Never select a soft-deleted / disabled question into a real paper. Any
    # non-zero value counts as active (forward-compatible with future
    # 1/2/... schemes) — only 0 is excluded.
    where.append("q.is_active != 0")
    if paper_tags:
        where.append("(%s)" % " OR ".join("q.paper_tags LIKE ?" for _ in paper_tags))
        params += [f'%"{t}"%' for t in paper_tags]
    if intact:
        where.append("q.context_block_id IS NOT NULL")
        where.append("q.context_block_id IN (SELECT id FROM context_blocks WHERE is_active != 0)")
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
    difficulties = list(cfg.get("difficulty") or [])
    paper_tags = list(cfg.get("paper_tags") or [])

    # A paper may span ONE or MORE subjects. `subjects` (a list of per-subject
    # configs) each carry their own sections/chapters/target; difficulty + mode
    # stay global. Single-subject config (subject/sections/chapters at top level)
    # is wrapped into a one-item list.
    subj_cfgs = cfg.get("subjects")
    if not subj_cfgs:
        subj_cfgs = [{
            "subject": cfg.get("subject"), "sections": cfg.get("sections"),
            "chapters": cfg.get("chapters"), "target_mode": cfg.get("target_mode"),
            "target_value": cfg.get("target_value"), "include_types": cfg.get("include_types"),
        }]

    sections_out = []
    blocks = {}
    subjects_used = []
    first_book = None

    for sc in subj_cfgs:
        books = books_for_class(con, class_number, sc.get("subject"))
        if not books:
            warnings.append("no book for class %s%s" % (
                class_number, " subject '%s'" % sc.get("subject") if sc.get("subject") else ""))
            continue
        book = books[0]
        first_book = first_book or book
        if book.get("subject") and book["subject"] not in subjects_used:
            subjects_used.append(book["subject"])
        secs, bl, ids, w = _select_for_book(con, book, [b["id"] for b in books], sc, difficulties, paper_tags, usage_map, rng, mode, strategy)
        for s in secs:
            s["subject"] = book.get("subject")
        sections_out += secs
        blocks.update(bl)
        chosen_ids += ids
        warnings += w

    if not first_book:
        raise ValueError(f"no book found for class {class_number}")

    # continuous display numbering across the whole paper
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

    multi = len(subjects_used) > 1
    content = {
        "exam_type": "cbse",
        "paper_title": cfg.get("paper_title", f"Class {first_book.get('class_level','')}"),
        "class_label": first_book.get("class_level"), "class_number": class_number,
        "subject": " · ".join(subjects_used) if multi else (subjects_used[0] if subjects_used else None),
        "subjects": subjects_used,
        "multi_subject": multi,
        "book_title": None if multi else first_book.get("title"),
        "exam_duration": cfg.get("exam_duration", "3 Hours"),
        "purpose": cfg.get("purpose", "exam"),
        "output_format": cfg.get("output_format", "pdf"),
        "exam_date": cfg.get("exam_date"),
        "watermark": bool(cfg.get("watermark", True)),
        "max_marks": round(max_marks, 1),
        "two_column": bool(cfg.get("two_column", True)),
        "show_question_marks": bool(cfg.get("show_question_marks", True)),
        "sections": sections_out, "context_blocks": blocks, "warnings": warnings,
    }
    return content, chosen_ids


def _select_for_book(con, book, book_ids, sc, difficulties, paper_tags, usage_map, rng, mode, strategy):
    """Run the blueprint selection for ONE subject (possibly several books)."""
    chapter_ids = [int(x) for x in (sc.get("chapters") or [])]
    chmap = {c["id"]: c["name"] for c in chapters_for_books(con, book_ids)}
    warnings, chosen, sections_out, blocks = [], [], [], {}

    target_mode = sc.get("target_mode") or "blueprint"
    if target_mode in ("marks", "questions"):
        case_qs = _avg_case_questions(con, book_ids) if target_mode == "questions" else 1
        buckets, scale_warn = _scaled_buckets(
            target_mode, float(sc.get("target_value") or 0),
            sc.get("include_types"), case_qs, sc.get("sections"))
        if scale_warn:
            warnings.append(f"[{book.get('subject','')}] {scale_warn}")
    else:
        buckets = _bp.resolve_buckets({"sections": sc.get("sections")})

    # STRICT: per-chapter pins may never exceed the section's blueprint count.
    # (Auto-sized sections in target modes are bumped up to their pins instead —
    # the user never stated a count for those.)
    for bk in buckets:
        pinned = sum(int(v) for v in (bk.get("chapters") or {}).values())
        if pinned > bk["count"]:
            if bk.get("_fixed") is False:   # auto share of a target — grow to fit
                warnings.append(f"[{bk['key']}] auto count raised to {pinned} to fit the chapter pins.")
                bk["count"] = pinned
            else:
                raise ValueError(
                    f"section {bk['key']}: {pinned} questions pinned to chapters, "
                    f"but the section total is {bk['count']} — lower the pins or raise the section count.")

    for bk in buckets:
        rows = _candidates(con, book_ids, bk["types"], bk.get("marks"), chapter_ids, difficulties, bk["intact"], paper_tags)
        q_ids_ordered = []

        if bk["intact"]:
            by_ch = {}
            for r in rows:
                by_ch.setdefault(r["chapter_id"], {}).setdefault(r["context_block_id"], []).append(r)
            caps = {cid: len(bl) for cid, bl in by_ch.items()}
            take, w = _resolve_take(bk, caps, rng, strategy)
            warnings += [f"[{book.get('subject','')} {bk['key']}] {m}" for m in w]
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
            warnings += [f"[{book.get('subject','')} {bk['key']}] {m}" for m in w]
            for cid, k in take.items():
                for qid in _pick(mode, by_ch[cid], k, usage_map, rng):
                    q_ids_ordered.append((qid, (cid, 0, 0)))

        q_ids_ordered.sort(key=lambda t: t[1])
        questions = []
        for qid, _k in q_ids_ordered:
            q = fetch_full_question(con, qid)
            q["section_marks"] = None if bk["intact"] else bk["marks"]
            q["_chapter_name"] = chmap.get(q.get("chapter_id"))
            questions.append(q)
            chosen.append(qid)

        sections_out.append({
            "code": bk["code"], "title": bk["title"], "instruction": bk["instruction"],
            "marks_per": bk["marks"], "intact_blocks": bk["intact"], "questions": questions,
        })

    # Questions target: case blocks print a variable number of sub-questions, so
    # after selection top up (or trim) the NON-case sections to land exactly on
    # the requested printed-question count.
    if target_mode == "questions":
        tgt = int(float(sc.get("target_value") or 0))
        printed = sum(len(s["questions"]) for s in sections_out)
        if tgt > 0 and printed < tgt:
            need = tgt - printed
            # top up AUTO sections first; user-pinned sections only as a last
            # resort, and never into a chapter the user pinned an exact count on
            pairs = sorted(zip(buckets, sections_out),
                           key=lambda t: (t[0].get("_fixed", False), t[0]["intact"]))
            for bk, sec in pairs:
                if need <= 0 or bk["intact"]:
                    continue
                rows = _candidates(con, book_ids, bk["types"], bk.get("marks"), chapter_ids, difficulties, False, paper_tags)
                have = {q["id"] for q in sec["questions"]}
                pinned_ch = set(int(c) for c in (bk.get("chapters") or {}))
                pool = [r for r in rows if r["id"] not in have and r["chapter_id"] not in pinned_ch]
                for qid in _pick(mode, pool, need, usage_map, rng):
                    q = fetch_full_question(con, qid)
                    q["section_marks"] = bk["marks"]
                    q["_chapter_name"] = chmap.get(q.get("chapter_id"))
                    sec["questions"].append(q)
                    chosen.append(qid)
                    need -= 1
            if need > 0:
                warnings.append(f"[{book.get('subject','')}] questions target {tgt}: only {tgt - need} available.")
        elif tgt > 0 and printed > tgt:
            extra = printed - tgt
            for bk, sec in zip(reversed(buckets), reversed(sections_out)):
                while extra > 0 and not bk["intact"] and sec["questions"]:
                    q = sec["questions"].pop()
                    if q["id"] in chosen:
                        chosen.remove(q["id"])
                    extra -= 1

    # Drop sections that ended up empty, then re-letter the remaining ones
    # sequentially (A, B, C, ...) so a filtered paper never shows gaps like
    # "Section A" followed by "Section E".
    sections_out = [s for s in sections_out if s["questions"]]
    relabel = {}
    for s in sections_out:
        old = s["code"]
        if old not in relabel:
            relabel[old] = chr(ord("A") + len(relabel))
        new = relabel[old]
        if new != s["code"]:
            if s.get("title"):
                s["title"] = f"Section {new}"
            s["code"] = new
    return sections_out, blocks, chosen, warnings


def _avg_case_questions(con, book_ids):
    """Average printed sub-questions per case block across these books (>=1)."""
    ph = ",".join("?" for _ in book_ids)
    row = _db.one(con, f"""
        SELECT CAST(COUNT(*) AS REAL) / MAX(COUNT(DISTINCT q.context_block_id), 1) AS a
        FROM questions q JOIN chapters c ON q.chapter_id = c.id
        WHERE c.book_id IN ({ph}) AND q.context_block_id IS NOT NULL""", list(book_ids))
    return max(1, int(round((row or {}).get("a") or 0)) or 1)


def _scaled_buckets(target_mode, target_value, include_types=None, case_qs=1, sections=None):
    """Plan section counts to hit a target total (marks or printed questions).

    Sections the user pinned (an explicit `count` in `sections`) keep that
    count; the REMAINDER of the target is distributed across the untouched
    sections proportionally to the default blueprint (floor + largest
    fractional remainder, only adding units that still fit). Explicit
    per-chapter maps ride along on each bucket. Returns (buckets, warn).

    target_mode 'marks': a unit of bucket b weighs b.marks marks.
    target_mode 'questions': a unit weighs 1 printed question — except intact
    case buckets, where one block prints ~case_qs numbered sub-questions.
    """
    buckets = _bp.default_blueprint()
    if include_types:
        inc = set(include_types)
        buckets = [b for b in buckets if inc.intersection(b["types"])]
    if not buckets:
        return [], "no blueprint sections match the included question types."

    overrides = sections or {}
    for b in buckets:
        ov = overrides.get(b["key"]) or {}
        if ov.get("chapters"):
            b["chapters"] = {int(k): int(v) for k, v in ov["chapters"].items()}
        b["_fixed"] = ov.get("count") is not None
        if b["_fixed"]:
            b["count"] = int(ov["count"])

    if not target_value or target_value <= 0:
        return [b for b in buckets if b["count"] > 0], None

    def unit(b):
        if target_mode == "marks":
            return b["marks"]          # intact case blocks carry marks_per per BLOCK
        return case_qs if b["intact"] else 1

    unit_name = "marks" if target_mode == "marks" else "questions"
    fixed_total = sum(b["count"] * unit(b) for b in buckets if b["_fixed"])
    remaining = target_value - fixed_total
    auto = [b for b in buckets if not b["_fixed"]]

    warn = None
    if remaining < 0:
        warn = (f"section counts already total {int(fixed_total)} {unit_name}, above the "
                f"target of {int(target_value)}; the explicit counts were kept.")
        for b in auto:
            b["count"] = 0
    elif auto:
        cur = sum(b["count"] * unit(b) for b in auto)
        f = remaining / cur if cur else 0
        fracs = []
        for b in auto:
            exact = b["count"] * f
            b["count"] = int(exact)
            fracs.append(exact - b["count"])
        residual = remaining - sum(b["count"] * unit(b) for b in auto)
        order = sorted(range(len(auto)), key=lambda i: -fracs[i])
        progress = True
        while residual > 0 and progress:
            progress = False
            for i in order:
                if unit(auto[i]) <= residual:
                    auto[i]["count"] += 1
                    residual -= unit(auto[i])
                    progress = True
        if residual > 0:
            warn = (f"target of {int(target_value)} {unit_name} not exactly reachable; "
                    f"paper is planned for {int(target_value - residual)}.")
    elif remaining > 0:
        warn = (f"section counts total {int(fixed_total)} {unit_name} but the target is "
                f"{int(target_value)}; leave some sections blank to auto-fill the rest.")

    return [b for b in buckets if b["count"] > 0], warn


def _resolve_take(bucket, caps, rng, strategy):
    """Per-chapter counts for a bucket.

    Hybrid: chapters with an explicit count get exactly that (capped by
    availability); whatever remains of the bucket count is spread evenly
    across the OTHER selected chapters. No explicit map => pure equal split.
    """
    explicit = bucket.get("chapters") or {}
    if not explicit:
        return equal_allocate(bucket["count"], caps, rng, strategy)

    take, warns = {}, []
    for cid, want in explicit.items():
        avail = caps.get(cid, 0)
        got = min(int(want), avail)
        if got < want:
            warns.append(f"chapter {cid} wanted {want}, only {got} available.")
        if got > 0:
            take[cid] = got

    remainder = int(bucket["count"]) - sum(int(v) for v in explicit.values())
    if remainder > 0:
        rest_caps = {cid: n for cid, n in caps.items() if cid not in explicit}
        if not rest_caps:  # every chapter got an explicit count — top up capacity-wise
            rest_caps = {cid: caps.get(cid, 0) - take.get(cid, 0) for cid in caps}
            rest_caps = {c: n for c, n in rest_caps.items() if n > 0}
        extra, w2 = equal_allocate(remainder, rest_caps, rng, strategy)
        warns += w2
        for cid, n in extra.items():
            take[cid] = take.get(cid, 0) + n
    return take, warns
