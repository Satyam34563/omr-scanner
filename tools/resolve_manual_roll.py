"""
Finishes sheets that were set aside for manual roll-number review.

Workflow:
  1. main.py writes manual_review.xlsx for any sheet whose roll number
     couldn't be read cleanly or didn't match a real student. Each row
     has a cropped image of that sheet's roll-number grid.
  2. A person opens manual_review.xlsx, looks at each image, and types
     the correct roll number into the "Actual Roll No" column, then
     saves the file.
  3. Run this script. For every row with an "Actual Roll No" filled
     in, it looks up that roll number in the school's student database,
     reconstructs the sheet's scoring from results.xlsx (no re-scanning
     needed - the detected answers are already in the "Answer Detail"
     sheet), and updates their row in results.xlsx (Roll No, student
     info, Needs Manual Roll Review).

This is a thin wrapper around omr/pipeline.py's resolve_manual_review()
- the same function the web API's POST /resolve endpoint calls (used
by the web review table instead of an Excel file) - so both ways of
resolving a sheet share identical scoring logic. This script's only
job is turning manual_review.xlsx into the same
{filename: roll_number} corrections dict the API takes as plain JSON.

Usage:
    python tools/resolve_manual_roll.py --results output/results.xlsx --manual-review output/manual_review.xlsx --config config.json --reports-pdf output/student_reports.pdf
"""

import argparse
import json
import os
import sys

import openpyxl

# Allow running as `python tools/resolve_manual_roll.py` from the project
# root: Python puts this script's own directory (tools/) on sys.path[0],
# not the project root, so the `omr` package (one level up) wouldn't be
# importable without this.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omr.pipeline import resolve_manual_review


def _read_manual_review(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Manual Review"] if "Manual Review" in wb.sheetnames else wb.active
    header = [str(c.value).strip() if c.value else "" for c in ws[1]]
    filename_col = header.index("Filename")
    actual_roll_col = header.index("Actual Roll No")

    corrections = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        filename = row[filename_col]
        actual_roll = row[actual_roll_col]
        if filename and actual_roll:
            corrections[str(filename)] = str(actual_roll).strip()
    return corrections


def main():
    parser = argparse.ArgumentParser(description="Resolve manually-reviewed roll numbers")
    parser.add_argument("--results", default="output/results.xlsx")
    parser.add_argument("--manual-review", default="output/manual_review.xlsx")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--reports-pdf", default="output/student_reports.pdf",
                         help="Output path for the single PDF containing every student's result")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    corrections = _read_manual_review(args.manual_review)
    if not corrections:
        print("No rows in manual_review.xlsx have an 'Actual Roll No' filled in yet.")
        return

    result = resolve_manual_review(args.results, corrections, config, args.reports_pdf)

    for r in result["resolved"]:
        print(f"Resolved '{r['filename']}' -> roll {r['roll_no']} ({r['name']})")

    print(f"\n{result['num_resolved']} sheet(s) resolved.")
    if result["reports_pdf_path"]:
        print(f"Combined PDF rebuilt: {result['reports_pdf_path']}")
    if result["num_still_pending"]:
        print(f"{result['num_still_pending']} sheet(s) still need a roll number.")
    if result["still_invalid"]:
        print(f"{len(result['still_invalid'])} entered roll number(s) still not found in student records - re-check these:")
        for item in result["still_invalid"]:
            print(f"  {item['filename']}: entered '{item['entered_roll']}'")


if __name__ == "__main__":
    main()
