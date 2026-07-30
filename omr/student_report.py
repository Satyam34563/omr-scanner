"""
Student result PDF - one combined output file for the whole batch.

Builds one professional, letterhead-branded, black-and-white result
page per scanned sheet - meant to be printed and physically handed to
students, so there is no background shading or color anywhere;
correct/incorrect/blank is conveyed by the text label itself (and bold
weight for anything that needs attention), not by color, so it reads
identically on a black-and-white printer.

Layout: school letterhead, student info (from the school's own
records - see omr/student_info.py), a summary panel, and the full
question-by-question table in the same 4-column style as the OMR
sheet itself. A question with more than one shaded bubble, or more
than one correct answer, is shown as e.g. "C D" rather than a single
letter.

Rendered via WeasyPrint (the same engine used for the master OMR sheet
PDF), from an HTML/CSS template built in Python - no browser needed.
Every student's page is rendered in memory and merged directly into a
single combined PDF (build_combined_report()) - no per-student files
are ever written to disk, so the output is just the one PDF.

Sheets still waiting on manual roll-number verification (see
omr/manual_review.py) aren't included yet - build_combined_report()
skips them until they're resolved via tools/resolve_manual_roll.py,
which rebuilds this same combined file, since the student's identity
isn't known yet.
"""

import base64
import html
import io
import os
from datetime import datetime

from pypdf import PdfWriter
from weasyprint import HTML

from omr.answer_key import format_clauses

VERDICT_LABEL = {
    "correct": "Correct",
    "wrong": "Incorrect",
    "unattempted": "Blank",
    "bonus": "Bonus",
}


def _image_data_uri(path):
    if not path or not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    if ext == "jpg":
        ext = "jpeg"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/{ext};base64,{encoded}"


def _fmt_answer(ans_tuple):
    return " ".join(ans_tuple) if ans_tuple else "-"


def _question_cells(per_question, num_columns=4):
    """Split the per-question verdicts into `num_columns` vertical
    blocks (like the OMR sheet's own 4-column layout) and render each
    as an HTML table."""
    per_col = (len(per_question) + num_columns - 1) // num_columns
    columns_html = []
    any_resolved = any(entry.get("resolved") for entry in per_question)
    for c in range(num_columns):
        chunk = per_question[c * per_col:(c + 1) * per_col]
        rows = []
        for entry in chunk:
            label = VERDICT_LABEL.get(entry["verdict"], "?")
            if entry["verdict"] == "wrong":
                row_class = "wrong-row"
            elif entry["verdict"] == "bonus":
                row_class = "bonus-row"
            else:
                row_class = ""
            your_answer = html.escape(_fmt_answer(entry["student_answer"]))
            if entry.get("resolved"):
                your_answer += "*"
            rows.append(
                f'<tr class="{row_class}">'
                f'<td class="qnum">{entry["question"]}</td>'
                f'<td class="ans">{your_answer}</td>'
                f'<td class="ans">{html.escape(format_clauses(entry["correct_answer"]))}</td>'
                f'<td class="verdict">{label}</td>'
                f"</tr>"
            )
        columns_html.append(
            '<table class="qtable">'
            "<thead><tr><th>Q</th><th>Your</th><th>Key</th><th>Result</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    grid_html = "".join(f'<div class="qcol">{c}</div>' for c in columns_html)
    return grid_html, any_resolved


def build_report_html(student_result, config):
    s = student_result["summary"]
    roll_no = student_result["roll_no"] or "PENDING VERIFICATION"
    filename = student_result["filename"]
    needs_review = student_result["needs_review"]
    info = student_result.get("student_info") or {}

    logo_uri = _image_data_uri(config.get("school_logo"))
    logo_html = f'<img class="logo" src="{logo_uri}">' if logo_uri else ""

    photo_uri = _image_data_uri(info.get("photo_path"))
    photo_html = (
        f'<img class="student-photo" src="{photo_uri}">' if photo_uri
        else '<div class="student-photo student-photo-placeholder">No Photo</div>'
    )

    review_banner = (
        '<div class="review-banner">FLAGGED FOR MANUAL REVIEW - roll number could not be '
        "automatically verified against student records.</div>"
        if needs_review else ""
    )

    max_marks = s["max_marks"]
    percentage = s["percentage"]

    student_info_html = ""
    if info:
        class_section = "/".join(p for p in [info.get("class", ""), info.get("section", "")] if p)
        student_info_html = f"""
        <div class="student-name-row"><span class="lbl">Name:</span> {html.escape(info.get('name', ''))}</div>
        <div class="student-info">
          <div><span class="lbl">Father's Name:</span> {html.escape(info.get('father_name', ''))}</div>
          <div><span class="lbl">Class/Section:</span> {html.escape(class_section)}</div>
          <div><span class="lbl">ID No:</span> {html.escape(info.get('id_no', ''))}</div>
        </div>
        """

    bonus_stat_html = (
        f'<div class="stat"><div class="stat-label">Bonus</div><div class="stat-value">{s["bonus"]}</div></div>'
        if s.get("bonus") else ""
    )
    summary_html = f"""
    <div class="summary-primary">
      <div class="stat-big"><div class="stat-label">Marks Obtained</div><div class="stat-value huge">{s['marks_obtained']} / {max_marks}</div></div>
      <div class="stat-big"><div class="stat-label">Percentage</div><div class="stat-value huge">{percentage}%</div></div>
    </div>
    <div class="summary-grid">
      <div class="stat"><div class="stat-label">Attempted</div><div class="stat-value">{s['attempted']} / {s['total_questions']}</div></div>
      <div class="stat"><div class="stat-label">Correct</div><div class="stat-value">{s['correct']}</div></div>
      <div class="stat"><div class="stat-label">Wrong</div><div class="stat-value">{s['wrong']}</div></div>
      <div class="stat"><div class="stat-label">Unattempted</div><div class="stat-value">{s['unattempted']}</div></div>
      {bonus_stat_html}
    </div>
    """

    generated_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

    qgrid_html, any_resolved = _question_cells(student_result["per_question"])
    resolved_note_html = (
        '<div>* More than one bubble was shaded for a single-answer question - '
        "scored using the most confidently-filled option.</div>"
        if any_resolved else ""
    )

    return f"""
<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>OMR Result - Roll {html.escape(str(roll_no))}</title>
<style>
  @page {{ size: A4 portrait; margin: 15mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "DejaVu Sans", Arial, sans-serif; color: #000; margin: 0; }}

  .header {{ display: flex; align-items: center; gap: 11mm; border-bottom: 0.6mm solid #000; padding-bottom: 3mm; }}
  .logo {{ width: 16mm; height: 16mm; object-fit: contain; flex-shrink: 0; }}
  .school-info {{ padding-left: 1mm; }}
  .school-name {{ font-family: Georgia, "DejaVu Serif", serif; font-size: 15pt; font-weight: bold; }}
  .school-sub {{ font-size: 7.5pt; margin-top: 0.5mm; }}

  .title-bar {{ text-align: center; font-size: 11pt; font-weight: bold; letter-spacing: 0.6mm;
                border-bottom: 0.4mm solid #000; padding: 2mm 0; margin-top: 3mm; }}

  .review-banner {{ border: 0.5mm solid #000; font-size: 8pt; font-weight: bold; text-align: center;
                     padding: 1.5mm; margin-top: 2mm; }}

  .info-photo-row {{ display: flex; align-items: flex-start; gap: 5mm; margin-top: 3mm; }}
  .info-text {{ flex: 1; min-width: 0; }}

  .meta-row {{ display: flex; justify-content: space-between; font-size: 9pt; }}
  .meta-row div span {{ font-weight: bold; }}

  .student-name-row {{ font-size: 11pt; margin-top: 2.5mm; border-top: 0.2mm solid #999; padding-top: 2mm; }}
  .student-name-row .lbl {{ font-weight: bold; }}
  .student-info {{ display: flex; flex-wrap: wrap; gap: 5mm; font-size: 9pt; margin-top: 1.2mm; }}
  .student-info .lbl {{ font-weight: bold; }}

  .student-photo {{ flex-shrink: 0; width: 22mm; height: 27mm; object-fit: cover; border: 0.4mm solid #000; }}
  .student-photo-placeholder {{ display: flex; align-items: center; justify-content: center; text-align: center;
                                 font-size: 7pt; color: #666; }}

  .summary-primary {{ display: flex; gap: 2.5mm; margin-top: 4mm; page-break-inside: avoid; }}
  .stat-big {{ flex: 1; border: 0.5mm solid #000; padding: 3mm 4mm; text-align: center; }}

  .summary-grid {{ display: flex; gap: 2.5mm; margin-top: 2.5mm; page-break-inside: avoid; }}
  .stat {{ flex: 1; border: 0.3mm solid #000; padding: 2mm 3mm; text-align: center; }}

  .stat-label {{ font-size: 7pt; text-transform: uppercase; letter-spacing: 0.2mm; }}
  .stat-value {{ font-size: 12pt; font-weight: bold; margin-top: 0.8mm; }}
  .stat-value.huge {{ font-size: 22pt; margin-top: 1.5mm; }}

  .qgrid {{ display: flex; gap: 3mm; margin-top: 4mm; border-top: 0.3mm solid #000; padding-top: 2mm; }}
  .qcol {{ flex: 1; page-break-inside: avoid; }}
  table.qtable {{ width: 100%; border-collapse: collapse; font-size: 7pt; }}
  table.qtable th {{ text-align: left; border-bottom: 0.3mm solid #000; padding: 0.7mm 1mm; font-size: 7pt; }}
  table.qtable td {{ padding: 0.6mm 1mm; border-bottom: 0.15mm solid #999; }}
  table.qtable tr {{ page-break-inside: avoid; }}
  table.qtable tr.wrong-row td {{ font-weight: bold; }}
  table.qtable tr.bonus-row td {{ font-style: italic; }}
  table.qtable td.qnum {{ font-weight: bold; width: 12%; }}
  table.qtable td.ans {{ width: 18%; text-align: center; }}
  table.qtable td.verdict {{ width: 30%; font-weight: bold; }}

  .footer {{ margin-top: 5mm; border-top: 0.3mm solid #000; padding-top: 2mm; font-size: 7pt; }}
  .footer .source-file {{ margin-top: 1mm; }}
</style></head>
<body>

  <div class="header">
    {logo_html}
    <div class="school-info">
      <div class="school-name">{html.escape(config.get('school_name', ''))}</div>
      <div class="school-sub">{html.escape(config.get('school_address', ''))}</div>
      <div class="school-sub">{html.escape(config.get('school_recognition', ''))}</div>
      <div class="school-sub">{config.get('school_contact', '')}</div>
    </div>
  </div>

  <div class="title-bar">OMR RESULT SHEET</div>
  {review_banner}

  <div class="info-photo-row">
    <div class="info-text">
      <div class="meta-row">
        <div>Roll No.: <span>{html.escape(str(roll_no))}</span></div>
        <div>Generated: <span>{generated_at}</span></div>
      </div>
      {student_info_html}
    </div>
    {photo_html}
  </div>

  {summary_html}

  <div class="qgrid">
    {qgrid_html}
  </div>

  <div class="footer">
    <div>Machine-generated result from OMR scan. For discrepancies, contact the examination cell with the physical answer sheet.</div>
    {resolved_note_html}
    <div class="source-file">Source File: {html.escape(filename)}</div>
  </div>

</body></html>
"""


def render_student_pdf_bytes(student_result, config):
    """Renders one student's result page and returns it as PDF bytes
    (nothing written to disk) - used so the whole batch can be merged
    directly into a single combined PDF without ever creating a
    separate file per student."""
    html_str = build_report_html(student_result, config)
    return HTML(string=html_str, base_url=os.getcwd()).write_pdf()


def _roll_sort_key(student_result):
    """Sorts numerically by roll number where it's purely numeric (the
    normal case), falling back to plain alphabetical order otherwise."""
    roll_no = student_result["roll_no"] or ""
    try:
        return (0, int(roll_no), "")
    except ValueError:
        return (1, 0, str(roll_no))


def build_combined_report(student_results, config, out_path):
    """Builds the single output PDF: every RESOLVED student's result
    (roll_no known), one after another in roll-number order, merged
    into one file at `out_path`. Sheets still pending manual roll
    review are skipped - see tools/resolve_manual_roll.py, which
    rebuilds this same combined file once they're resolved. Returns
    (out_path, skipped_filenames); out_path is None if nothing was
    resolved yet."""
    resolved = [r for r in student_results if r["roll_no"] is not None]
    skipped = [r["filename"] for r in student_results if r["roll_no"] is None]
    if not resolved:
        return None, skipped

    resolved.sort(key=_roll_sort_key)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    writer = PdfWriter()
    for student_result in resolved:
        pdf_bytes = render_student_pdf_bytes(student_result, config)
        writer.append(io.BytesIO(pdf_bytes))
    with open(out_path, "wb") as f:
        writer.write(f)
    writer.close()
    return out_path, skipped
