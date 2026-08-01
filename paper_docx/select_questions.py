#!/usr/bin/env python3
"""
select_questions.py — Stage 1 of the question-paper pipeline.

Reads questions.db + a JSON config describing which sections/chapters/passages
to pull and how many questions from each, resolves the actual question set,
and writes a self-contained paper_content.json that the docx renderer
(build_docx.js) consumes.

Usage:
    python3 select_questions.py --db /path/questions.db --config config.json \
        --image-base /path/to/QUESTION_BANK --out paper_content.json

Config schema — see README.md for full docs. Quick shape:

{
  "paper_title": "Mental Ability & Arithmetic Test",
  "output_name": "sample_paper",
  "exam_duration": "2 Hours",        // ask the user for this before generating; defaults to "2 Hours"
  "numbering": "continuous" | "per_section",
  "selection_mode": "sequential" | "random",
  "random_seed": 42,
  "shortfall_strategy": "redistribute" | "allow_shortfall",
  "sections": [
    {
      "section_name": "MENTAL ABILITY TEST",
      "total_questions": 40,
      "chapters": null                 // null/{} => equal split across all chapters with available Qs
    },
    {
      "section_name": "ARITHMETIC TEST",
      "total_questions": 20,
      "chapters": {"Number and Numeric System": 5, "Average": 0}   // explicit counts (optional)
    },
    {
      "section_name": "LANGUAGE TEST (ENGLISH)",
      "mode": "passages",
      "num_passages": 4,
      "questions_per_passage": null    // null => include every question tied to the chosen passage
    }
  ]
}
"""
import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict


def load_config(path):
    with open(path) as f:
        return json.load(f)


def get_conn(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def resolve_equal_split(chapter_counts_available, total_target, strategy, rng):
    """
    chapter_counts_available: dict chapter_name -> available question count
    total_target: desired total number of questions for the section
    strategy: "redistribute" or "allow_shortfall"
    rng: random.Random instance — WHICH chapters receive the remainder/
         redistributed extras is randomized (not always the first chapters
         in chapter_number order), even though the equal-split math itself
         (base = total_target // n_chapters) is unchanged.

    Returns dict chapter_name -> count_to_take, and a list of warning strings.
    """
    warnings = []
    chapters = [c for c, n in chapter_counts_available.items() if n > 0]
    zero_chapters = [c for c, n in chapter_counts_available.items() if n == 0]
    if zero_chapters:
        warnings.append(
            f"Chapters with 0 available questions skipped: {zero_chapters}"
        )

    if not chapters:
        return {}, warnings + ["No chapters had any available questions."]

    n_chapters = len(chapters)
    base = total_target // n_chapters
    remainder = total_target % n_chapters

    take = {c: min(base, chapter_counts_available[c]) for c in chapters}
    # distribute remainder one at a time — which chapters get the +1 is
    # randomized so it's not always the first N chapters by chapter_number.
    order = list(chapters)
    rng.shuffle(order)
    idx = 0
    r = remainder
    guard = 0
    while r > 0 and guard < 10000:
        c = order[idx % len(order)]
        if take[c] < chapter_counts_available[c]:
            take[c] += 1
            r -= 1
        idx += 1
        guard += 1

    shortfall = total_target - sum(take.values())
    if shortfall > 0:
        if strategy == "redistribute":
            # give leftover capacity to chapters that still have unused
            # questions — order randomized rather than sorted by capacity,
            # so the same chapters aren't always favored.
            capacity = {c: chapter_counts_available[c] - take[c] for c in chapters}
            capacity = {c: v for c, v in capacity.items() if v > 0}
            cap_order = list(capacity.keys())
            rng.shuffle(cap_order)
            i = 0
            while shortfall > 0 and cap_order:
                c = cap_order[i % len(cap_order)]
                if take[c] < chapter_counts_available[c]:
                    take[c] += 1
                    shortfall -= 1
                cap_order = [c2 for c2 in cap_order if take[c2] < chapter_counts_available[c2]]
                if not cap_order:
                    break
                i += 1
            if shortfall > 0:
                warnings.append(
                    f"Could not reach target of {total_target}; database only has "
                    f"{sum(chapter_counts_available.values())} questions available "
                    f"across chapters in this section. Short by {shortfall}."
                )
        else:
            warnings.append(
                f"Shortfall of {shortfall} allowed (allow_shortfall strategy); "
                f"section will have {sum(take.values())} questions instead of {total_target}."
            )

    return {c: v for c, v in take.items() if v > 0}, warnings


def fetch_chapter_question_ids(cur, chapter_id):
    cur.execute(
        "SELECT id FROM questions WHERE chapter_id=? ORDER BY question_number ASC",
        (chapter_id,),
    )
    return [r["id"] for r in cur.fetchall()]


def pick_n(ids, n, mode, rng):
    if n >= len(ids):
        return list(ids)
    if mode == "random":
        return sorted(rng.sample(ids, n))
    return ids[:n]


LETTERS = ["a", "b", "c", "d", "e", "f"]


def fetch_full_question(cur, qid):
    cur.execute("SELECT * FROM questions WHERE id=?", (qid,))
    q = dict(cur.fetchone())
    cur.execute("SELECT label, text, image FROM options WHERE question_id=? ORDER BY label ASC", (qid,))
    opts = [dict(r) for r in cur.fetchall()]

    # RULE: options are always relabeled a, b, c, d... regardless of how the
    # source book labeled them (some sub-types use 1/2/3/4). Order is
    # preserved (options were already fetched in ascending original-label
    # order), so position i just gets LETTERS[i]. correct_answer is remapped
    # from the *original* label to the new letter by matching position, so
    # the answer key stays consistent with what's printed on the paper.
    original_correct = (q.get("correct_answer") or "").strip().lower()
    new_correct = None
    for i, opt in enumerate(opts):
        orig_label = (opt.get("label") or "").strip().lower()
        new_label = LETTERS[i] if i < len(LETTERS) else opt["label"]
        if orig_label == original_correct:
            new_correct = new_label
        opt["label"] = new_label
    if new_correct:
        q["correct_answer"] = new_correct

    q["options"] = opts
    q["question_images"] = json.loads(q["question_images"] or "[]")
    if q["context_block_id"]:
        cur.execute("SELECT * FROM context_blocks WHERE id=?", (q["context_block_id"],))
        cb = cur.fetchone()
        q["_context_block"] = dict(cb) if cb else None
    else:
        q["_context_block"] = None
    return q


def build_section_mental_arith(cur, sec_cfg, strategy, mode, rng, warnings):
    section_name = sec_cfg["section_name"]
    cur.execute("SELECT id FROM sections WHERE name=?", (section_name,))
    srow = cur.fetchone()
    if not srow:
        warnings.append(f"Section '{section_name}' not found in DB — skipped.")
        return None
    section_id = srow["id"]

    cur.execute(
        "SELECT id, name, chapter_number FROM chapters WHERE section_id=? ORDER BY chapter_number ASC",
        (section_id,),
    )
    chapters = [dict(r) for r in cur.fetchall()]
    chapter_ids_by_name = {c["name"]: c["id"] for c in chapters}

    available = {}
    ids_by_chapter = {}
    for c in chapters:
        ids = fetch_chapter_question_ids(cur, c["id"])
        ids_by_chapter[c["name"]] = ids
        available[c["name"]] = len(ids)

    explicit = sec_cfg.get("chapters")
    if explicit:
        # explicit counts given — validate against availability, no auto-redistribution
        take_counts = {}
        for cname, want in explicit.items():
            if cname not in available:
                warnings.append(f"Chapter '{cname}' not found in section '{section_name}' — skipped.")
                continue
            got = min(want, available[cname])
            if got < want:
                warnings.append(
                    f"'{cname}' requested {want} but only {got} available in DB."
                )
            if got > 0:
                take_counts[cname] = got
    else:
        total_target = sec_cfg.get("total_questions")
        if total_target is None:
            warnings.append(
                f"Section '{section_name}' has no 'chapters' and no 'total_questions' — skipped."
            )
            return None
        take_counts, w = resolve_equal_split(available, total_target, strategy, rng)
        warnings.extend(w)

    questions = []
    for cname, n in take_counts.items():
        ids = ids_by_chapter[cname]
        chosen = pick_n(ids, n, mode, rng)
        for qid in chosen:
            q = fetch_full_question(cur, qid)
            q["_chapter_name"] = cname
            questions.append(q)

    # stable order: by chapter_number, then question_number
    chapter_order = {c["name"]: c["chapter_number"] for c in chapters}
    questions.sort(key=lambda q: (chapter_order.get(q["_chapter_name"], 999), q["question_number"]))

    return {
        "section_name": section_name,
        "questions": questions,
        "take_counts": take_counts,
    }


def build_section_passages(cur, sec_cfg, mode, rng, warnings):
    section_name = sec_cfg["section_name"]
    cur.execute("SELECT id FROM sections WHERE name=?", (section_name,))
    srow = cur.fetchone()
    if not srow:
        warnings.append(f"Section '{section_name}' not found in DB — skipped.")
        return None
    section_id = srow["id"]

    cur.execute(
        """
        SELECT DISTINCT cb.id, cb.text
        FROM context_blocks cb
        JOIN questions q ON q.context_block_id = cb.id
        JOIN chapters c ON q.chapter_id = c.id
        WHERE c.section_id = ? AND cb.category = 'reading_comprehension'
        ORDER BY cb.id ASC
        """,
        (section_id,),
    )
    passages = [dict(r) for r in cur.fetchall()]
    if not passages:
        warnings.append(f"No reading-comprehension passages found for section '{section_name}'.")
        return None

    explicit_ids = sec_cfg.get("passage_ids")
    if explicit_ids:
        by_id = {p["id"]: p for p in passages}
        missing = [i for i in explicit_ids if i not in by_id]
        if missing:
            warnings.append(
                f"Section '{section_name}': passage_ids not found in DB: {missing}"
            )
        passages = [by_id[i] for i in explicit_ids if i in by_id]
        if not passages:
            warnings.append(f"Section '{section_name}': no valid passage_ids — skipped.")
            return None

    num_passages = sec_cfg.get("num_passages", len(passages))
    num_passages = min(num_passages, len(passages))
    if mode == "random":
        chosen_passages = rng.sample(passages, num_passages)
    else:
        chosen_passages = passages[:num_passages]

    per_passage_cap = sec_cfg.get("questions_per_passage")

    questions = []
    for p in chosen_passages:
        cur.execute(
            "SELECT id FROM questions WHERE context_block_id=? ORDER BY question_number ASC",
            (p["id"],),
        )
        qids = [r["id"] for r in cur.fetchall()]
        if per_passage_cap:
            qids = pick_n(qids, per_passage_cap, mode, rng)
        for qid in qids:
            q = fetch_full_question(cur, qid)
            cur.execute(
                "SELECT c.name FROM chapters c JOIN questions qq ON qq.chapter_id=c.id WHERE qq.id=?",
                (qid,),
            )
            crow = cur.fetchone()
            q["_chapter_name"] = crow["name"] if crow else None
            q["_passage_id"] = p["id"]
            questions.append(q)

    return {
        "section_name": section_name,
        "questions": questions,
        "passages_used": [p["id"] for p in chosen_passages],
    }


# --- Krutidev->Unicode legacy-font artifact cleanup (Hindi source books) ---
# Ordered: longest/most-specific first. Only unambiguous garbles are mapped.
import re as _re

KRUTIDEV_FIXES = [
    ("राष्Vª", "राष्ट्र"),
    ("दृषि्V", "दृष्टि"),
    ("Vª", "ट्र"),          # Vªाम->ट्राम
    ("टª", "ट्र"),           # मेटªो->मेट्रो
    ("बãपुत्र", "ब्रह्मपुत्र"),
    ("ã", "ह्म"),            # ब्रãाण्ड->ब्रह्माण्ड
    ("11वेंद्ध", "11वें)"),
    ("वैंळ", "कैं"),          # वैंळपाकोला->कैंपाकोला
    ("वैळ", "कै"),           # वैळसे->कैसे
    ("व्रूळ", "क्रू"),        # व्रूळर->क्रूर
    ("वू्रळ", "क्रू"),
    ("वूळ", "कू"),           # अनुवूळल->अनुकूल
    ("वुळ", "कु"),           # वुळछ->कुछ
    ("वृळ", "कृ"),           # कलावृळति->कलाकृति
    ("वेळ", "के"),           # वेळवल->केवल, उनवेळ->उनके
    ("पेंळ", "फें"),          # पेंळक->फेंक
    ("पेळं", "फें"),
    ("पैळ", "फै"),           # पैळला->फैला
    ("पेळ", "फे"),           # पेळरें->फेरें
    ("Iय", "प्य"),           # Iयार->प्यार, Iयास->प्यास
    ("शु:", "शुरू"),          # शु: की गई->शुरू की गई
]
# lone V after a Devanagari half-form / vowel sign -> ट (स्पष्V, ऊँV, ...)
_V_RE = _re.compile(r"(?<=[ऀ-ॿ])V")
# lone ':' directly followed by a Devanagari letter -> रू (:प->रूप, ज:री->जरूरी)
_COLON_RE = _re.compile(r":(?=[क-ह])")
# leaked "<line-number> द्य" junk (Krutidev '|' danda + verse numbers) -> drop
_DIGIT_DYA_RE = _re.compile(r"\s*\d+\s*द्य")


def fix_devanagari_text(s):
    if not s or not isinstance(s, str):
        return s
    for bad, good in KRUTIDEV_FIXES:
        s = s.replace(bad, good)
    s = _V_RE.sub("ट", s)
    s = _COLON_RE.sub("रू", s)
    s = _DIGIT_DYA_RE.sub("", s)
    return s


def deep_fix_devanagari(obj):
    """In-place fix of every string value in a question dict (stem, options,
    explanation, context block text) — skips image paths and non-strings."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "image" or k.endswith("_images"):
                continue  # never touch file paths
            if isinstance(v, str):
                obj[k] = fix_devanagari_text(v)
            else:
                deep_fix_devanagari(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                obj[i] = fix_devanagari_text(v)
            else:
                deep_fix_devanagari(v)


def dedupe_context_blocks(all_questions):
    """Collapse repeated context_block usage into a blocks dict + question->block_id map."""
    blocks = {}
    for q in all_questions:
        cb = q.get("_context_block")
        if cb:
            blocks[cb["id"]] = {
                "id": cb["id"],
                "type": cb["type"],
                "category": cb["category"],
                "text": cb["text"],
            }
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--image-base", required=True, help="Folder containing images/ (QUESTION_BANK root)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    con = get_conn(args.db)
    cur = con.cursor()

    mode = cfg.get("selection_mode", "random")
    strategy = cfg.get("shortfall_strategy", "redistribute")
    rng = random.Random(cfg.get("random_seed", 42))

    warnings = []
    sections_out = []

    for sec_cfg in cfg["sections"]:
        if sec_cfg.get("mode") == "passages":
            result = build_section_passages(cur, sec_cfg, mode, rng, warnings)
        else:
            result = build_section_mental_arith(cur, sec_cfg, strategy, mode, rng, warnings)
        if result:
            sections_out.append(result)

    # assign display numbering
    numbering = cfg.get("numbering", "continuous")
    counter = 1
    for sec in sections_out:
        if numbering == "per_section":
            counter = 1
        for q in sec["questions"]:
            q["display_number"] = counter
            counter += 1

    # resolve image paths to absolute
    import os
    for sec in sections_out:
        for q in sec["questions"]:
            q["question_images"] = [os.path.join(args.image_base, p) for p in q["question_images"]]
            for opt in q["options"]:
                if opt.get("image"):
                    opt["image"] = os.path.join(args.image_base, opt["image"])

    # normalize Krutidev->Unicode conversion artifacts in all text
    for sec in sections_out:
        for q in sec["questions"]:
            deep_fix_devanagari(q)

    # dedupe context blocks across the whole paper
    all_qs = [q for sec in sections_out for q in sec["questions"]]
    blocks = dedupe_context_blocks(all_qs)
    for q in all_qs:
        q["context_block_id"] = q["_context_block"]["id"] if q.get("_context_block") else None
        q.pop("_context_block", None)

    total_questions = sum(len(sec["questions"]) for sec in sections_out)

    output = {
        "paper_title": cfg.get("paper_title", "Question Paper"),
        "output_name": cfg.get("output_name", "question_paper"),
        "exam_duration": cfg.get("exam_duration") or "2 Hours",
        "exam_date": cfg.get("exam_date") or None,
        "total_questions": total_questions,
        "sections": sections_out,
        "context_blocks": blocks,
        "warnings": warnings,
    }

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Selected {total_questions} questions across {len(sections_out)} sections.")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(" -", w)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
