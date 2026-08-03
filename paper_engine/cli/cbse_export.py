"""
cli/cbse_export.py — OMR answer-key .xlsx for a CBSE paper (for checking OMR
sheets, same format as the competitive one). Only the OMR-checkable questions
(those with options — MCQ / assertion-reason) are included; their `Question`
number is the on-paper display number (Section A is first, so 1..M line up with
the OMR bubbles).

    python3 -m cli.cbse_export --content cbse_content.json --out omr.xlsx [--negative 0]
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--negative", type=float, default=0.0)  # CBSE: usually no negative marking
    args = ap.parse_args()

    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AnswerKey"
    ws.append(["Question", "Answer", "Marks", "Negative Marks", "Is Bonus", "Is Multi Correct"])

    n = 0
    for sec in content.get("sections", []):
        for q in sec.get("questions", []):
            if not q.get("options"):
                continue  # not OMR-checkable
            ans = (q.get("correct_answer_display") or "").strip().lower() or None
            marks = q.get("section_marks") or q.get("marks") or 1
            ws.append([q.get("display_number"), ans, marks, args.negative, 0, 0])
            n += 1

    wb.save(args.out)
    print(f"wrote {args.out} ({n} OMR questions)")


if __name__ == "__main__":
    main()
