"""
exports.py — extra downloadable deliverables built from paper_content.json:

  • OMR answer key (.xlsx)  — the exact sheet the OMR checker consumes:
      sheet "AnswerKey", columns Question | Answer | Marks | Negative Marks |
      Is Bonus | Is Multi Correct, one row per question numbered 1..N in paper
      order (stays valid even under per-section numbering).

  • Question metadata report (.pdf) — provenance of every question: which
      book/section, chapter, original question number, source page, exercise
      label, type, marks, PYQ exam/year, answer, status.

openpyxl + weasyprint come from the OMR venv (see services.paper.export_python).
"""
import html as _html

ANSWER_HEADERS = ["Question", "Answer", "Marks", "Negative Marks", "Is Bonus", "Is Multi Correct"]


def _iter_questions(content):
    """Yield (paper_index 1..N, section_name, question) in paper order."""
    idx = 0
    for sec in content.get("sections", []):
        name = sec.get("section_name")
        for q in sec.get("questions", []):
            idx += 1
            yield idx, name, q


# ---------------------------------------------------------------- answer key
def write_answer_key_xlsx(content, path, marks=1.5, negative=0.25):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AnswerKey"
    ws.append(ANSWER_HEADERS)
    for idx, _sec, q in _iter_questions(content):
        ans = (q.get("correct_answer") or "").strip().lower() or None
        ws.append([idx, ans, marks, negative, 0, 0])
    wb.save(path)


# --------------------------------------------------------------- metadata pdf
_COLS = [
    ("n", "#"), ("book", "Book / Section"), ("chapter", "Chapter"),
    ("orig", "Orig. Q#"), ("page", "Page"), ("exercise", "Exercise"),
    ("type", "Type"), ("marks", "Marks"), ("pyq", "PYQ (exam · year)"),
    ("answer", "Ans"), ("status", "Status"),
]


def _rows(content):
    out = []
    for idx, sec_name, q in _iter_questions(content):
        pyq = ""
        if q.get("is_pyq"):
            parts = [p for p in [q.get("pyq_exam"),
                                 str(q["pyq_year"]) if q.get("pyq_year") else None] if p]
            pyq = " · ".join(parts)
        marks = q.get("marks")
        out.append({
            "n": idx,
            "book": sec_name or "",
            "chapter": q.get("_chapter_name") or "",
            "orig": q.get("question_number") if q.get("question_number") is not None else "",
            "page": q.get("source_page") if q.get("source_page") is not None else "",
            "exercise": q.get("exercise_label") or "",
            "type": q.get("type") or "",
            "marks": "" if marks is None else (int(marks) if float(marks).is_integer() else marks),
            "pyq": pyq,
            "answer": (q.get("correct_answer") or "").upper(),
            "status": q.get("answer_status") or "",
        })
    return out


def _render_html(content, rows):
    title = _html.escape(content.get("paper_title") or "Question Paper")
    head = "".join(f"<th>{_html.escape(lbl)}</th>" for _k, lbl in _COLS)
    body = []
    for r in rows:
        cells = "".join(f"<td>{_html.escape(str(r[k]))}</td>" for k, _lbl in _COLS)
        body.append(f"<tr>{cells}</tr>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @page {{ size: A4 landscape; margin: 12mm; }}
      * {{ font-family: "Noto Sans", "Noto Sans Devanagari", "Arial Unicode MS", sans-serif; }}
      h1 {{ font-size: 15px; margin: 0 0 2px; }}
      .sub {{ font-size: 10px; color: #555; margin: 0 0 10px; }}
      table {{ width: 100%; border-collapse: collapse; font-size: 9px; }}
      th, td {{ border: 0.5px solid #bbb; padding: 3px 4px; text-align: left;
               vertical-align: top; word-break: break-word; }}
      th {{ background: #efefef; font-weight: 600; }}
      td:first-child, th:first-child {{ text-align: right; width: 26px; }}
    </style></head><body>
      <h1>{title} — Question Metadata Report</h1>
      <p class="sub">{len(rows)} questions · source provenance for each</p>
      <table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>
    </body></html>"""


def write_metadata_pdf(content, path):
    from weasyprint import HTML

    HTML(string=_render_html(content, _rows(content))).write_pdf(path)
