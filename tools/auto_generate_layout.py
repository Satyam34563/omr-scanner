"""
Fully automatic layout generator - NO manual clicking required.

This replaces the old click-based omr/calibrate.py for any sheet that
has printed registration markers and bubbles (like
html_answer_sheet/omr_sheet.html/.pdf). It works by rendering the
clean master PDF (a perfect vector drawing, no camera noise) and
detecting every marker and bubble programmatically:

  1. The 4 solid corner squares (registration markers) are found by
     looking for filled, roughly-square blobs of the right size.
  2. Every answer/roll bubble is found by looking for the small
     circular *hole* inside each bubble's ring. Detecting the hole
     (via contour hierarchy) instead of the ring itself is what makes
     this robust even though rows are packed tightly enough that
     neighbouring bubbles visually touch (their outer ink rings merge
     into one blob, but each bubble's interior hole stays separate).
  3. All detected bubble centers are clustered by position (largest
     gaps first) into the roll-number grid (6 digit-columns x 10
     values) and the 100-question grid (4 column-blocks x 25 rows x
     4 options), using the known structure of this template.

Run this ONCE (it's already been run and its output committed as
layout.json) - only re-run it if the sheet template itself changes
(e.g. you edit omr_sheet.html/css and regenerate the PDF).

Usage:
    python tools/auto_generate_layout.py --pdf html_answer_sheet/omr_sheet.pdf --output layout.json --dpi 200

Marker/bubble size ranges below are computed from the sheet's actual
printed dimensions (mm, from html_answer_sheet/generate_html_sheet.py)
and the render DPI, rather than hardcoded pixel constants tied to one
specific bubble size - so re-running this after changing bubble size,
marker size, or DPI in the sheet generator "just works" without also
having to hand-tune magic numbers here.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

NUM_ROLL_DIGITS = 6
NUM_ROLL_VALUES = 10
NUM_QUESTIONS = 100
NUM_BLOCKS = 4
ROWS_PER_BLOCK = 25
OPTIONS = ["A", "B", "C", "D"]

# Must match html_answer_sheet/generate_html_sheet.py's GEOMETRY block.
MARKER_SIZE_MM = 6.0
BUBBLE_DIAMETER_MM = 5.0 * 0.7   # BASE_BUBBLE_D * BUBBLE_SCALE
BUBBLE_BORDER_MM = 0.35          # --bubble-border


def _mm_to_px(mm, dpi):
    return mm * dpi / 25.4


def _marker_area_range(dpi, tolerance=0.20):
    side = _mm_to_px(MARKER_SIZE_MM, dpi)
    area = side * side
    return (area * (1 - tolerance), area * (1 + tolerance))


def _bubble_hole_area_range(dpi, tolerance=0.35):
    """The bubble is detected by its interior HOLE, not its outer ring
    (see find_bubble_centers below) - the hole's radius is the printed
    bubble's radius minus its border stroke width."""
    bubble_r = _mm_to_px(BUBBLE_DIAMETER_MM, dpi) / 2
    border = _mm_to_px(BUBBLE_BORDER_MM, dpi)
    hole_r = max(1.0, bubble_r - border)
    area = np.pi * hole_r ** 2
    return (area * (1 - tolerance), area * (1 + tolerance))


def render_pdf_to_image(pdf_path, dpi):
    with tempfile.TemporaryDirectory() as tmp:
        out_prefix = str(Path(tmp) / "page")
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-singlefile", pdf_path, out_prefix],
            check=True,
        )
        img = cv2.imread(out_prefix + ".png")
        if img is None:
            raise RuntimeError("Failed to render PDF to image (is poppler-utils/pdftoppm installed?)")
        return img


def find_markers(binary, marker_area_range):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    markers = []
    for c in contours:
        area = cv2.contourArea(c)
        x, y, w, h = cv2.boundingRect(c)
        if w == 0 or h == 0:
            continue
        aspect = w / h
        extent = area / (w * h)
        if 0.9 < aspect < 1.1 and extent > 0.9 and marker_area_range[0] < area < marker_area_range[1]:
            markers.append((x + w / 2, y + h / 2))
    return markers


def find_bubble_centers(binary, bubble_hole_area_range):
    """Detect bubbles via their interior hole, not their outer ring
    (rings in tightly-packed rows visually touch; holes never do)."""
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    hierarchy = hierarchy[0] if hierarchy is not None else []
    centers = []
    for i, c in enumerate(contours):
        if hierarchy[i][3] == -1:
            continue  # top-level contour, not a hole
        area = cv2.contourArea(c)
        if not (bubble_hole_area_range[0] < area < bubble_hole_area_range[1]):
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w == 0 or h == 0:
            continue
        aspect = w / h
        perimeter = cv2.arcLength(c, True)
        circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0
        # Now that bubbles are printed smaller, their hole size range
        # overlaps the sheet's small square UI checkboxes (Present/
        # Absent) closely enough in AREA alone to need a real shape
        # check to tell them apart: a square hole's ideal circularity is
        # pi/4 (~0.785, measured ~0.83 here after antialiasing), while
        # even a slightly-pixelated circular bubble hole at this size
        # still measures notably higher (~0.84+) - 0.83 sits in the gap
        # between the two.
        if 0.8 < aspect < 1.2 and circularity > 0.83:
            centers.append((x + w / 2, y + h / 2))
    return centers


def cluster_1d(vals, k):
    """Split a list of scalar positions into k ordered groups by
    cutting at the k-1 largest gaps between sorted values. Returns
    groups of indices into the original `vals` list, ordered
    low-to-high."""
    idx_sorted = sorted(range(len(vals)), key=lambda i: vals[i])
    sorted_vals = [vals[i] for i in idx_sorted]
    gaps = [(sorted_vals[i + 1] - sorted_vals[i], i) for i in range(len(sorted_vals) - 1)]
    gaps.sort(reverse=True)
    cut_points = sorted(g[1] for g in gaps[: k - 1])
    groups, start = [], 0
    for cp in cut_points:
        groups.append(idx_sorted[start: cp + 1])
        start = cp + 1
    groups.append(idx_sorted[start:])
    return groups


def build_layout(image, dpi):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    marker_area_range = _marker_area_range(dpi)
    bubble_hole_area_range = _bubble_hole_area_range(dpi)

    markers = find_markers(binary, marker_area_range)
    if len(markers) != 4:
        raise RuntimeError(f"Expected 4 registration markers, found {len(markers)}. "
                            f"Check MARKER_SIZE_MM against this render's DPI ({dpi}).")

    bubbles = find_bubble_centers(binary, bubble_hole_area_range)
    expected_total = NUM_ROLL_DIGITS * NUM_ROLL_VALUES + NUM_QUESTIONS * len(OPTIONS)
    if len(bubbles) != expected_total:
        raise RuntimeError(f"Expected {expected_total} bubbles, found {len(bubbles)}. "
                            f"Check BUBBLE_DIAMETER_MM against this render's DPI ({dpi}).")

    # Split into roll-grid vs question-grid: the roll grid sits above
    # the question grid with a large vertical gap between them - find
    # the single largest y-gap among all bubbles to separate the two.
    bubbles.sort(key=lambda p: p[1])
    ys = [p[1] for p in bubbles]
    gaps = [(ys[i + 1] - ys[i], i) for i in range(len(ys) - 1)]
    split_at = max(gaps)[1]
    roll_pts = bubbles[: split_at + 1]
    q_pts = bubbles[split_at + 1:]

    expected_roll = NUM_ROLL_DIGITS * NUM_ROLL_VALUES
    if len(roll_pts) != expected_roll or len(q_pts) != NUM_QUESTIONS * len(OPTIONS):
        raise RuntimeError(
            f"Roll/question split looks wrong: {len(roll_pts)} roll pts "
            f"(expected {expected_roll}), {len(q_pts)} question pts "
            f"(expected {NUM_QUESTIONS * len(OPTIONS)})."
        )

    # --- Roll grid: 10 rows (digit values 0-9, top to bottom) x 6 columns (digit position 1-6, left to right)
    roll_layout = {}
    row_groups = cluster_1d([p[1] for p in roll_pts], NUM_ROLL_VALUES)
    for value, g in enumerate(row_groups):
        row_pts = sorted((roll_pts[i] for i in g), key=lambda p: p[0])
        if len(row_pts) != NUM_ROLL_DIGITS:
            raise RuntimeError(f"Roll grid row for value {value} has {len(row_pts)} points, expected {NUM_ROLL_DIGITS}")
        for position, (x, y) in enumerate(row_pts, start=1):
            roll_layout.setdefault(str(position), {})[str(value)] = [float(x), float(y)]

    # --- Question grid: 4 column-blocks (Q1-25 / 26-50 / 51-75 / 76-100) x 25 rows x 4 options
    question_layout = {}
    col_groups = cluster_1d([p[0] for p in q_pts], NUM_BLOCKS)
    for block_idx, g in enumerate(col_groups):
        block_pts = [q_pts[i] for i in g]
        row_groups = cluster_1d([p[1] for p in block_pts], ROWS_PER_BLOCK)
        for row_idx, rg in enumerate(row_groups):
            row_pts = sorted((block_pts[i] for i in rg), key=lambda p: p[0])
            if len(row_pts) != len(OPTIONS):
                raise RuntimeError(
                    f"Block {block_idx} row {row_idx} has {len(row_pts)} bubbles, expected {len(OPTIONS)}"
                )
            q_num = block_idx * ROWS_PER_BLOCK + row_idx + 1
            question_layout[str(q_num)] = {
                OPTIONS[k]: [float(row_pts[k][0]), float(row_pts[k][1])] for k in range(len(OPTIONS))
            }

    # Order markers TL, TR, BR, BL for perspective correction downstream
    markers_sorted = sorted(markers, key=lambda p: (p[1], p[0]))
    top_two = sorted(markers_sorted[:2], key=lambda p: p[0])
    bottom_two = sorted(markers_sorted[2:], key=lambda p: p[0])
    tl, tr = top_two
    bl, br = bottom_two

    bubble_radius = _mm_to_px(BUBBLE_DIAMETER_MM, dpi) / 2

    return {
        "canonical_width": image.shape[1],
        "canonical_height": image.shape[0],
        "bubble_radius": round(bubble_radius, 1),
        "markers": {
            "tl": list(tl), "tr": list(tr), "br": list(br), "bl": list(bl),
        },
        "roll_grid": {
            "num_digits": NUM_ROLL_DIGITS,
            "num_values": NUM_ROLL_VALUES,
            "bubbles": roll_layout,
        },
        "bubbles": question_layout,
    }


def main():
    parser = argparse.ArgumentParser(description="Auto-generate layout.json from the clean master PDF (no manual clicking)")
    parser.add_argument("--pdf", required=True, help="Path to the master OMR sheet PDF")
    parser.add_argument("--output", default="layout.json")
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    image = render_pdf_to_image(args.pdf, args.dpi)
    layout = build_layout(image, args.dpi)

    with open(args.output, "w") as f:
        json.dump(layout, f, indent=2)

    print(f"Auto-calibrated layout saved to {args.output}")
    print(f"  canonical size: {layout['canonical_width']}x{layout['canonical_height']} @ {args.dpi} DPI")
    print(f"  bubble radius: {layout['bubble_radius']}px")
    print(f"  markers: {layout['markers']}")
    print(f"  {len(layout['bubbles'])} questions, {len(layout['roll_grid']['bubbles'])} roll-digit positions")


if __name__ == "__main__":
    main()
