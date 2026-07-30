"""
DEV/TEST UTILITY (not needed for normal use).

Generates realistic synthetic "photographed" copies of the REAL sheet
(html_answer_sheet/omr_sheet.pdf) with known answers/roll numbers
already bubbled in, so the full pipeline - marker-based dewarping,
question detection, AND roll-number detection - can be verified
end-to-end without a real printer/camera.

One of the generated scans is deliberately rotated, skewed, and pasted
onto a larger plain background (simulating a phone photo taken at a
slight angle) to specifically exercise find_registration_markers().

Usage:
    python tools/generate_test_scans.py
"""

import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import img2pdf
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPTIONS = ["A", "B", "C", "D"]


def render_master(pdf_path, dpi):
    with tempfile.TemporaryDirectory() as tmp:
        prefix = str(Path(tmp) / "page")
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", pdf_path, prefix], check=True)
        return cv2.imread(prefix + ".png")


def fill_bubble(img, x, y, radius):
    cv2.circle(img, (int(x), int(y)), max(2, int(round(radius)) - 4), (20, 20, 20), -1)


def render_filled_sheet(base_img, layout, roll_digits, answers, multi_answers=(), blank_roll_positions=()):
    """
    roll_digits: list of 6 ints, or None for a position to leave unbubbled
        (simulates an ambiguous/unclear roll digit).
    answers: {question_num: "C"} for single-answer, or {question_num: "BC"}
        (any string containing the letters) for a multi-select response.
    """
    img = base_img.copy()
    radius = layout.get("bubble_radius", 20)

    for pos_str, values in layout["roll_grid"]["bubbles"].items():
        pos = int(pos_str)
        if pos in blank_roll_positions:
            continue
        digit = roll_digits[pos - 1]
        x, y = values[str(digit)]
        fill_bubble(img, x, y, radius)

    for q_str, options in layout["bubbles"].items():
        q_num = int(q_str)
        chosen = answers.get(q_num)
        if not chosen:
            continue
        for letter in chosen:
            x, y = options[letter]
            fill_bubble(img, x, y, radius)

    return img


def simulate_photo(img, rotate_deg=3.5, pad_frac=0.12):
    """Paste the sheet onto a larger gray background with a slight
    rotation, to mimic a phone photo and exercise marker detection
    under non-canonical, non-axis-aligned conditions."""
    h, w = img.shape[:2]
    pad_x, pad_y = int(w * pad_frac), int(h * pad_frac)
    canvas_w, canvas_h = w + 2 * pad_x, h + 2 * pad_y
    canvas = np.full((canvas_h, canvas_w, 3), 180, dtype=np.uint8)
    canvas[pad_y:pad_y + h, pad_x:pad_x + w] = img

    center = (canvas_w / 2, canvas_h / 2)
    matrix = cv2.getRotationMatrix2D(center, rotate_deg, 1.0)
    rotated = cv2.warpAffine(canvas, matrix, (canvas_w, canvas_h),
                              borderValue=(180, 180, 180))
    return rotated


def main():
    random.seed(7)

    with open(PROJECT_ROOT / "config.json") as f:
        config = json.load(f)
    with open(PROJECT_ROOT / "layout.json") as f:
        layout = json.load(f)

    pdf_path = str(PROJECT_ROOT / config["sheet_pdf"])
    base_img = render_master(pdf_path, config["render_dpi"])
    if base_img.shape[1] != layout["canonical_width"] or base_img.shape[0] != layout["canonical_height"]:
        sys.exit("Re-rendered master size doesn't match layout.json - regenerate layout.json first.")

    out_dir = PROJECT_ROOT / "demo" / "real_sheet_scans"
    out_dir.mkdir(parents=True, exist_ok=True)

    num_questions = config["num_questions"]

    # Build a key with a couple of deliberate multi-answer questions.
    key_answers = {}
    for q in range(1, num_questions + 1):
        key_answers[q] = random.choice(OPTIONS)
    key_answers[5] = "BC"    # Q5: correct answer is B AND C
    key_answers[42] = "AD"   # Q42: correct answer is A AND D

    def build_answers(match_key=True, blank_rate=0.05, wrong_multi_q5=False):
        answers = {}
        for q in range(1, num_questions + 1):
            if random.random() < blank_rate:
                continue
            if match_key:
                answers[q] = key_answers[q]
            else:
                answers[q] = random.choice(OPTIONS)
        if wrong_multi_q5:
            answers[5] = "B"  # only shades one of the two correct options -> should mark WRONG
        return answers

    ground_truth = {"key_answers": key_answers, "students": {}}

    students = [
        {
            "label": "valid_260471", "roll_digits": [2, 6, 0, 4, 7, 1],
            "answers": build_answers(match_key=True, blank_rate=0.05, wrong_multi_q5=True),
            "blank_roll_positions": [], "distort": False,
        },
        {
            "label": "not_in_db_999999", "roll_digits": [9, 9, 9, 9, 9, 9],
            "answers": build_answers(match_key=False, blank_rate=0.10),
            "blank_roll_positions": [], "distort": False,
        },
        {
            "label": "ambiguous_digit_26x471", "roll_digits": [2, 6, 0, 4, 7, 1],
            "answers": build_answers(match_key=False, blank_rate=0.10),
            "blank_roll_positions": [3], "distort": False,  # digit position 3 left unbubbled
        },
        {
            "label": "photo_260471", "roll_digits": [2, 6, 0, 4, 7, 1],
            "answers": build_answers(match_key=True, blank_rate=0.08),
            "blank_roll_positions": [], "distort": True,  # simulated phone photo
        },
    ]

    jpg_paths = []
    for student in students:
        filled = render_filled_sheet(
            base_img, layout, student["roll_digits"], student["answers"],
            blank_roll_positions=student["blank_roll_positions"],
        )
        if student["distort"]:
            filled = simulate_photo(filled)

        out_path = out_dir / f"{student['label']}.jpg"
        cv2.imwrite(str(out_path), filled)
        jpg_paths.append(str(out_path))
        ground_truth["students"][student["label"]] = {
            "roll_digits": student["roll_digits"],
            "blank_roll_positions": student["blank_roll_positions"],
            "answers": student["answers"],
        }
        print(f"Wrote {out_path.name} ({'simulated photo' if student['distort'] else 'clean scan'})")

    with open(out_dir / "ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    # Also combine every generated page into ONE multi-page PDF, in the
    # same page order as `students` - this is what the primary
    # "scan to PDF" input workflow (main.py --scans-pdf) expects, and
    # what the demo instructions in README.md now feed it. img2pdf
    # embeds the existing JPEG bytes directly (no re-encoding), so it
    # doesn't depend on Pillow's own JPEG codec being available.
    combined_pdf_path = out_dir / "scans.pdf"
    with open(combined_pdf_path, "wb") as f:
        f.write(img2pdf.convert(jpg_paths))
    print(f"Wrote {combined_pdf_path.name} (combined {len(jpg_paths)}-page scan PDF, page order = {[s['label'] for s in students]})")

    print(f"\n{len(students)} test scans + ground truth written to {out_dir}")


if __name__ == "__main__":
    main()
