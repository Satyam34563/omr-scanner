"""
fetch.py — pull candidate rows and full question records from questions.db.

fetch_full_question mirrors the original select_questions.py behavior exactly:
options are ALWAYS relabeled a,b,c,d... (some source sub-types use 1/2/3/4),
order preserved, and correct_answer remapped from the original label to the new
letter by position — so the printed paper and the answer key stay consistent.
"""
import json

from . import db
from .filters import build_where

LETTERS = ["a", "b", "c", "d", "e", "f"]


def candidate_rows(con, spec) -> list[dict]:
    """Eligible questions for a filter spec, as light rows for ranking.

    Includes context_block_id + cb_type so the unit-aware picker can keep
    intact blocks (passage / question_block) together.
    """
    where, params, join = build_where(spec)
    return db.dicts(
        con,
        f"SELECT q.id, q.question_number, q.type, q.pyq_year, "
        f"q.context_block_id, cb.type AS cb_type "
        f"FROM questions q{join} "
        f"LEFT JOIN context_blocks cb ON q.context_block_id = cb.id "
        f"WHERE {where}",
        params,
    )


def fetch_full_question(con, qid: int) -> dict:
    q = db.one(con, "SELECT * FROM questions WHERE id=?", (qid,))
    opts = db.dicts(
        con,
        "SELECT label, text, image FROM options WHERE question_id=? ORDER BY label ASC",
        (qid,),
    )

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
    q["question_images"] = json.loads(q.get("question_images") or "[]")

    if q.get("context_block_id"):
        cb = db.one(con, "SELECT * FROM context_blocks WHERE id=?", (q["context_block_id"],))
        q["_context_block"] = cb
    else:
        q["_context_block"] = None
    return q
