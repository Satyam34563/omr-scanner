"""
OMR Checker - command-line entry point.

Processes a whole batch of scanned/photographed answer sheets, detects
the darkened bubble(s) for each of the 100 questions plus the 6-digit
bubbled roll number, scores each sheet against an Excel answer key
(questions may have more than one correct answer), looks up each
validated student's official record from the school's own system, and
writes an Excel report plus a single branded PDF containing every
student's result, one page after another, in roll-number order.

Usage:
    python main.py
    (or override paths: python main.py --scans-pdf input/scans.pdf --answer-key input/answer_key.xlsx --output output/results.xlsx)

Requires layout.json to exist. It's generated fully automatically (no
manual clicking) from the clean master PDF:
    python tools/auto_generate_layout.py --pdf html_answer_sheet/omr_sheet.pdf --output layout.json

Scan input: put every filled-in sheet for the batch into ONE PDF at
`input/scans.pdf` (one page per sheet - exactly what a scanner's
"scan to PDF"/ADF feature produces). If that file doesn't exist, a
folder of separate image files (`input/scans/`) is used instead, kept
only as a fallback for anyone who still has individual scan files.

A sheet whose roll number can't be read cleanly, or reads cleanly but
doesn't match any real student, is NOT guessed at - it's set aside in
manual_review.xlsx (with a cropped image of its roll grid) for a
person to resolve. Run tools/resolve_manual_roll.py afterward to
finish those sheets once the correct roll numbers are filled in.

This is a thin wrapper around omr/pipeline.py's run_batch() - the same
function the web API (api.py) calls, so the CLI and the API always run
identical logic.
"""

import argparse
import sys

from omr.pipeline import run_batch, load_config_and_layout


def main():
    parser = argparse.ArgumentParser(description="Automated OMR sheet checker")
    parser.add_argument("--scans-pdf", default="input/scans.pdf",
                         help="Combined PDF with one scanned sheet per page (primary input)")
    parser.add_argument("--scans-dir", default="input/scans",
                         help="Fallback folder of separate scanned sheet images, used only if --scans-pdf doesn't exist")
    parser.add_argument("--answer-key", default="input/answer_key.xlsx", help="Excel file with the correct answers")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--layout", default="layout.json", help="Path to auto-generated layout.json")
    parser.add_argument("--output", default="output/results.xlsx", help="Output Excel report path")
    parser.add_argument("--reports-pdf", default="output/student_reports.pdf",
                         help="Output path for the single PDF containing every student's result")
    parser.add_argument("--manual-review", default="output/manual_review.xlsx",
                         help="Output path for sheets needing manual roll-number verification")
    parser.add_argument("--overlay-pdf", default="output/bubble_overlay.pdf",
                         help="Output path for the diagnostic PDF showing exactly where each bubble "
                              "was checked and what was detected (red=empty, green=filled answer, "
                              "orange=detected roll digit)")
    args = parser.parse_args()

    try:
        config, layout = load_config_and_layout(args.config, args.layout)
    except FileNotFoundError as e:
        sys.exit(str(e))

    def print_progress(filename, i, total, confirmed_roll, summary):
        if summary is None:
            return  # this sheet failed to process; the reason is already in warnings
        bonus_suffix = f"/{summary['bonus']}Bonus" if summary["bonus"] else ""
        print(f"{filename}: roll={confirmed_roll or 'PENDING REVIEW'} "
              f"marks={summary['marks_obtained']}/{summary['max_marks']} "
              f"({summary['correct']}C/{summary['wrong']}W/{summary['unattempted']}U{bonus_suffix})")

    try:
        result = run_batch(
            args.scans_pdf, args.scans_dir, args.answer_key, config, layout,
            args.output, args.reports_pdf, args.manual_review, args.overlay_pdf,
            progress_callback=print_progress,
        )
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(str(e))

    print(f"\nDone. {result['num_processed']} sheet(s) processed.")
    print(f"Excel report saved to: {result['output_path']}")
    if result["reports_pdf_path"]:
        print(f"{result['num_resolved']} result(s) saved to: {result['reports_pdf_path']}")
    if result["overlay_pdf_path"]:
        print(f"Bubble-detection overlay saved to: {result['overlay_pdf_path']}")
    if result["manual_review_path"]:
        print(f"{result['num_pending_review']} sheet(s) need manual roll verification - see {result['manual_review_path']}")
        print("After filling in 'Actual Roll No' there, run tools/resolve_manual_roll.py to finish them.")
    if result["warnings"]:
        print(f"{len(result['warnings'])} warning(s) - see the 'Warnings' sheet in the report.")


if __name__ == "__main__":
    main()
