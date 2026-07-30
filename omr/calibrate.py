"""
One-time interactive calibration tool.

Because bubble positions on the printed/scanned sheet depend on your
printer and scanner/camera, run this ONCE against a clear sample scan
(ideally a blank or lightly-filled sheet) to teach the checker exactly
where every bubble is. It writes `layout.json`, which every subsequent
run of main.py reuses.

Usage:
    python -m omr.calibrate --image scans/sample.jpg --config config.json --output layout.json

Controls (a window will pop up):
    - Click the exact CENTER of the bubble requested in the terminal/title.
    - Press 'u' to undo the last click.
    - Press 'q' to quit without saving.
Only works on a machine with a display (run it locally, not in a
headless server/sandbox).
"""

import argparse
import json

import cv2
import numpy as np

from .preprocessing import load_and_normalize

OPTIONS = ["A", "B", "C", "D"]


def _click_point(window_name, image, prompt):
    """Show `image` and block until the user left-clicks one point."""
    clicked = {}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked["pt"] = (x, y)

    display = image.copy()
    cv2.putText(display, prompt, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.imshow(window_name, display)
    cv2.setMouseCallback(window_name, on_mouse)

    while "pt" not in clicked:
        key = cv2.waitKey(20) & 0xFF
        if key == ord("q"):
            raise KeyboardInterrupt("Calibration cancelled by user")

    # Show a confirmation dot then briefly pause
    cv2.circle(display, clicked["pt"], 6, (0, 255, 0), -1)
    cv2.imshow(window_name, display)
    cv2.waitKey(200)
    return clicked["pt"]


def run_calibration(image_path, config):
    canonical_w = config["canonical_width"]
    canonical_h = config["canonical_height"]
    num_blocks = config["num_blocks"]
    rows_per_block = config["rows_per_block"]
    questions_per_block = config["questions_per_block"]

    warped = load_and_normalize(image_path, canonical_w, canonical_h)
    window = "Calibration - click requested bubble centers"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    # Step 1: block 1, question 1, option A and option D -> horizontal spacing
    ax, ay = _click_point(window, warped, "Click Q1 - option A bubble center")
    dx, dy = _click_point(window, warped, "Click Q1 - option D bubble center")
    col_xs = np.linspace(ax, dx, len(OPTIONS))

    # Step 2: block 1, last question (row 20), option A -> vertical spacing
    last_q_in_block = rows_per_block
    a20x, a20y = _click_point(window, warped, f"Click Q{last_q_in_block} - option A bubble center")
    row_ys = np.linspace(ay, a20y, rows_per_block)

    # Step 3: first question of every other block -> block x-offset
    block_a_x = [ax]
    for b in range(1, num_blocks):
        first_q = b * questions_per_block + 1
        bx, by = _click_point(window, warped, f"Click Q{first_q} - option A bubble center")
        block_a_x.append(bx)

    cv2.destroyAllWindows()

    # Build full bubble map
    col_offset_from_a = col_xs - ax  # offsets of B, C, D relative to A within a block
    bubbles = {}
    for b in range(num_blocks):
        block_a = block_a_x[b]
        for r in range(rows_per_block):
            q_num = b * questions_per_block + r + 1
            y = float(row_ys[r])
            bubbles[str(q_num)] = {
                OPTIONS[i]: [float(block_a + col_offset_from_a[i]), y]
                for i in range(len(OPTIONS))
            }

    layout = {
        "canonical_width": canonical_w,
        "canonical_height": canonical_h,
        "bubble_radius": max(8, int(abs(dx - ax) / (len(OPTIONS) * 2.2))),
        "bubbles": bubbles,
    }
    return layout


def main():
    parser = argparse.ArgumentParser(description="Calibrate OMR bubble layout from a sample scan")
    parser.add_argument("--image", required=True, help="Path to a sample scanned/photographed sheet")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--output", default="layout.json", help="Where to save the calibrated layout")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    layout = run_calibration(args.image, config)

    with open(args.output, "w") as f:
        json.dump(layout, f, indent=2)

    print(f"Saved layout for {len(layout['bubbles'])} questions to {args.output}")


if __name__ == "__main__":
    main()
