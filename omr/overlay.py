"""
Bubble-detection overlay PDF - a diagnostic/audit tool, not part of
scoring itself.

For every processed sheet, draws a marker at every position the
detector looked at (from layout.json), color-coded by what it decided:

  - thin red circle    = a bubble slot that was checked and found EMPTY
  - solid green circle  = a bubble slot that was checked and found FILLED
                          (selected as one of the student's answers)
  - solid orange circle = the roll-grid digit value read as the
                          bubbled digit for that position

This lets a person visually confirm, sheet by sheet, exactly where the
system looked for each bubble and what it concluded - the same red
"search here" circles used ad hoc during development to debug the real
scan detection issue, now made into a proper batch output.

One page per processed sheet, in the same order as the batch, combined
into a single PDF (matching the project's "one combined PDF per batch"
convention used for student_report.py).
"""

import cv2
import img2pdf
import numpy as np

RED = (0, 0, 255)      # BGR
GREEN = (0, 170, 0)
ORANGE = (0, 140, 255)
CAPTION_HEIGHT = 50


def _draw_question_overlay(img, layout, detected_answers):
    radius = int(round(layout.get("bubble_radius", 20)))
    for q_str, options in layout.get("bubbles", {}).items():
        q_num = int(q_str)
        selected = set(detected_answers.get(q_num, {}).get("answers", []))
        for opt, (x, y) in options.items():
            center = (int(round(x)), int(round(y)))
            if opt in selected:
                cv2.circle(img, center, radius, GREEN, -1)
                cv2.circle(img, center, radius, (0, 0, 0), 1)
            else:
                cv2.circle(img, center, radius, RED, 2)
    return img


def _draw_roll_overlay(img, layout, roll_per_digit):
    radius = int(round(layout.get("bubble_radius", 20)))
    roll_grid = layout.get("roll_grid", {})
    detected_by_pos = {d["position"]: d["value"] for d in (roll_per_digit or [])}

    for pos_str, values in roll_grid.get("bubbles", {}).items():
        pos = int(pos_str)
        detected_value = detected_by_pos.get(pos)
        for val_str, (x, y) in values.items():
            center = (int(round(x)), int(round(y)))
            if detected_value is not None and val_str == str(detected_value):
                cv2.circle(img, center, radius, ORANGE, -1)
                cv2.circle(img, center, radius, (0, 0, 0), 1)
            else:
                cv2.circle(img, center, radius, RED, 2)
    return img


def render_overlay_image(warped_bgr, layout, detected_answers, roll_per_digit, filename, roll_str=None):
    """Returns a new BGR image: the warped sheet with bubble-search
    overlays drawn on it, plus a caption strip identifying the sheet
    and a small legend."""
    img = warped_bgr.copy()
    _draw_question_overlay(img, layout, detected_answers)
    _draw_roll_overlay(img, layout, roll_per_digit)

    h, w = img.shape[:2]
    canvas = np.full((h + CAPTION_HEIGHT, w, 3), 255, dtype=np.uint8)
    canvas[CAPTION_HEIGHT:, :] = img

    label = f"{filename}   roll={roll_str or 'UNRESOLVED'}"
    cv2.putText(canvas, label, (15, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    legend = "red = checked, empty     green = detected fill     orange = detected roll digit"
    cv2.putText(canvas, legend, (15, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 60), 1, cv2.LINE_AA)
    return canvas


def build_overlay_pdf(pages, layout, out_path):
    """
    pages: list of (filename, warped_bgr, detected_answers, roll_per_digit, roll_str)
        - one entry per sheet that was successfully warped, in the
          order they should appear in the PDF.
    layout: the loaded layout.json dict (bubble positions/radius).
    Writes one combined PDF, one page per sheet. Returns out_path, or
    None if `pages` is empty.
    """
    if not pages:
        return None

    png_pages = []
    for filename, warped_bgr, detected_answers, roll_per_digit, roll_str in pages:
        overlay_img = render_overlay_image(
            warped_bgr, layout, detected_answers, roll_per_digit, filename, roll_str
        )
        ok, buf = cv2.imencode(".png", overlay_img)
        if not ok:
            continue
        png_pages.append(buf.tobytes())

    if not png_pages:
        return None

    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(png_pages))

    return out_path
