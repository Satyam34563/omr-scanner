"""
DEV/TEST UTILITY (not needed for normal use).

Generates a synthetic "scanned" OMR sheet image plus a matching
layout.json, so the pipeline can be tested end-to-end without a real
printer/scanner. Useful for verifying the install works, and for the
automated test in tests/test_pipeline.py.

Usage:
    python tools/generate_test_sheet.py
"""

import json
import os
import random

import cv2
import numpy as np

CANVAS_W, CANVAS_H = 1700, 2338
NUM_BLOCKS, ROWS_PER_BLOCK = 5, 20
MARGIN_X, MARGIN_TOP = 90, 260
BLOCK_GAP = 300
ROW_GAP = 95
OPT_GAP = 34
RADIUS = 13


def build_layout():
    bubbles = {}
    for b in range(NUM_BLOCKS):
        block_x0 = MARGIN_X + b * BLOCK_GAP + 40
        for r in range(ROWS_PER_BLOCK):
            q_num = b * ROWS_PER_BLOCK + r + 1
            y = MARGIN_TOP + r * ROW_GAP
            bubbles[str(q_num)] = {
                opt: [float(block_x0 + i * OPT_GAP), float(y)]
                for i, opt in enumerate(["A", "B", "C", "D"])
            }
    return {
        "canonical_width": CANVAS_W,
        "canonical_height": CANVAS_H,
        "bubble_radius": RADIUS,
        "bubbles": bubbles,
    }


def render_sheet(layout, student_answers, out_path):
    img = np.full((CANVAS_H, CANVAS_W, 3), 255, dtype=np.uint8)
    cv2.putText(img, "OMR ANSWER SHEET (SYNTHETIC TEST)", (MARGIN_X, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

    for q_str, options in layout["bubbles"].items():
        q_num = int(q_str)
        cv2.putText(img, f"{q_num}", (int(options["A"][0]) - 55, int(options["A"][1]) + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        for opt, (x, y) in options.items():
            cv2.circle(img, (int(x), int(y)), RADIUS, (0, 0, 0), 2)

        chosen = student_answers.get(q_num)
        if chosen:
            x, y = options[chosen]
            cv2.circle(img, (int(x), int(y)), RADIUS - 3, (0, 0, 0), -1)

    cv2.imwrite(out_path, img)


def main():
    random.seed(42)
    demo_dir = os.path.join(os.path.dirname(__file__), "..", "demo")
    out_dir = os.path.join(demo_dir, "scans")
    os.makedirs(out_dir, exist_ok=True)

    layout = build_layout()
    with open(os.path.join(demo_dir, "test_layout.json"), "w") as f:
        json.dump(layout, f, indent=2)

    ground_truth = {}
    options = ["A", "B", "C", "D"]

    for roll in [1, 2, 3]:
        answers = {}
        for q in range(1, 101):
            r = random.random()
            if r < 0.08:
                continue  # leave blank
            answers[q] = random.choice(options)
        ground_truth[roll] = answers
        render_sheet(layout, answers, os.path.join(out_dir, f"{roll}.jpg"))

    with open(os.path.join(demo_dir, "test_ground_truth.json"), "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"Generated {len(ground_truth)} synthetic test sheets in {out_dir}")


if __name__ == "__main__":
    main()
