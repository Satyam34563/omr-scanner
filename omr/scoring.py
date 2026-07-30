"""
Compares detected bubble answers against the answer key and computes
marks per student, plus aggregated per-question statistics across the
whole batch.

Each answer-key entry (see omr/answer_key.py) carries its own marks,
negative marks, bonus flag, and a DNF "clauses" list (a question can be
correct in more than one way - "A or B", "A and B", or a mix like
"A and B or C and D"). A question is "correct" only if the student's
shaded set exactly matches ONE of those clauses; a "Is Bonus" question
is always correct, for every student, regardless of what was shaded.
"""

import re


def extract_roll_number(filename, pattern):
    match = re.search(pattern, filename)
    return match.group(1) if match else None


def _is_correct(student_ans, clauses):
    student_set = frozenset(student_ans)
    return any(student_set == frozenset(clause) for clause in clauses)


def _is_single_pick(clauses):
    """True for a question where no acceptable answer ever requires more
    than one bubble at once - a plain single answer ("C"), or several
    single-letter alternatives ("A or B") both qualify; "A and B" (or
    any clause needing 2+ letters together) does not, since shading
    more than one bubble there is genuinely required, not accidental."""
    return bool(clauses) and all(len(clause) == 1 for clause in clauses)


def _resolve_student_answer(student_ans, ratios, clauses):
    """If this is a single-pick question (see above) and the student
    shaded more than one bubble - almost always an accidental double-
    mark, not an intentional multi-select, since the question was never
    going to accept more than one anyway - resolve it down to whichever
    of the shaded options was filled MOST confidently (highest measured
    ink-fill ratio) and grade against that alone, rather than failing
    the question outright for "wrong number of bubbles shaded."
    Returns (resolved_answer, was_resolved)."""
    if len(student_ans) <= 1 or not _is_single_pick(clauses):
        return student_ans, False
    best_opt = max(student_ans, key=lambda opt: ratios.get(opt, 0.0))
    return (best_opt,), True


def score_sheet(detected_answers, answer_key, marking_scheme, num_questions=100):
    """
    detected_answers: {q_num: {"answers": ["C"] or ["C","D"] or [], "ratios": {...}}}
    answer_key: {q_num: {"clauses": [...], "marks": float,
        "negative_marks": float, "is_bonus": bool, "is_multi_correct": bool}}
        - only questions present here are scored; anything the sheet
        has bubbles for but the key doesn't cover (e.g. an exam with
        fewer than 100 questions) is treated as not existing at all,
        not as "unattempted".
    marking_scheme: {"unattempted": 0.0, ...} - only "unattempted" is
        still read from here; "correct"/"wrong" marks are per-question
        (see answer_key.py), already defaulted from marking_scheme
        there if a question didn't specify its own.
    Returns a summary dict plus the per-question verdict list.
    """
    correct = wrong = unattempted = bonus_count = resolved_count = 0
    marks = 0.0
    max_marks = 0.0
    per_question = []

    active_questions = sorted(answer_key.keys())
    unattempted_marks = marking_scheme.get("unattempted", 0.0)

    for q in active_questions:
        entry = answer_key[q]
        clauses = entry["clauses"]
        q_marks = entry["marks"]
        max_marks += q_marks

        det = detected_answers.get(q, {"answers": [], "ratios": {}})
        raw_ans = tuple(sorted(det.get("answers", [])))
        student_ans, was_resolved = _resolve_student_answer(raw_ans, det.get("ratios", {}), clauses)
        if was_resolved:
            resolved_count += 1

        if entry["is_bonus"]:
            bonus_count += 1
            correct += 1
            marks += q_marks
            verdict = "bonus"
        elif not student_ans:
            unattempted += 1
            marks += unattempted_marks
            verdict = "unattempted"
        elif _is_correct(student_ans, clauses):
            correct += 1
            marks += q_marks
            verdict = "correct"
        else:
            wrong += 1
            marks -= entry["negative_marks"]
            verdict = "wrong"

        per_question.append({
            "question": q,
            "student_answer": student_ans,
            "raw_student_answer": raw_ans if was_resolved else student_ans,
            "resolved": was_resolved,
            "correct_answer": clauses,
            "verdict": verdict,
            "marks": q_marks,
            "negative_marks": entry["negative_marks"],
            "is_bonus": entry["is_bonus"],
        })

    # Bonus questions are always counted as "correct" for marks/facility
    # purposes regardless of what (if anything) was shaded, but that's
    # not the same as the student having genuinely attempted it - a
    # blank bonus question shouldn't inflate "attempted".
    attempted = correct + wrong - bonus_count

    summary = {
        "correct": correct,
        "wrong": wrong,
        "unattempted": unattempted,
        "bonus": bonus_count,
        "resolved_multi_marks": resolved_count,
        "attempted": attempted,
        "total_questions": len(active_questions),
        "marks_obtained": round(marks, 2),
        "max_marks": round(max_marks, 2),
        "percentage": round((marks / max_marks) * 100, 2) if max_marks else 0.0,
    }
    return summary, per_question


def aggregate_question_stats(all_per_question_results, answer_key, num_questions=100):
    """
    all_per_question_results: list of per_question lists (one per student).
    Only questions present in answer_key are included - a question the
    exam doesn't have (key entry missing) simply doesn't appear here.
    Returns per-question stats: option distribution + correct-answer % (facility index).
    """
    active_questions = sorted(answer_key.keys())
    stats = {
        q: {"A": 0, "B": 0, "C": 0, "D": 0, "unattempted": 0, "correct_count": 0}
        for q in active_questions
    }

    total_students = len(all_per_question_results)

    for per_question in all_per_question_results:
        for entry in per_question:
            q = entry["question"]
            if q not in stats:
                continue
            verdict = entry["verdict"]
            if verdict == "unattempted":
                stats[q]["unattempted"] += 1
            else:
                for opt in entry["student_answer"]:
                    if opt in stats[q]:
                        stats[q][opt] += 1
            if verdict in ("correct", "bonus"):
                stats[q]["correct_count"] += 1

    results = []
    for q in active_questions:
        s = stats[q]
        entry = answer_key[q]
        facility = round((s["correct_count"] / total_students) * 100, 1) if total_students else 0.0
        results.append({
            "question": q,
            "correct_answer": entry["clauses"],
            "marks": entry["marks"],
            "negative_marks": entry["negative_marks"],
            "is_bonus": entry["is_bonus"],
            "is_multi_correct": entry["is_multi_correct"],
            "A": s["A"], "B": s["B"], "C": s["C"], "D": s["D"],
            "unattempted": s["unattempted"],
            "correct_count": s["correct_count"],
            "facility_index_%": facility,
        })
    return results
