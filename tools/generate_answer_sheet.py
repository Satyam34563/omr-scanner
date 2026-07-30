"""
Generates the production-ready, print-quality OMR answer sheet (PDF + PNG
preview) for this project, along with the matching layout.json.

Unlike omr/calibrate.py (which teaches the checker where bubbles are by
having a human click them on a sample scan), this sheet is
AUTO-CALIBRATING: it's printed with 4 registration marks near the
corners - a filled circle at the true top-left and filled squares at the
other three corners. omr/preprocessing.find_fiducial_corners() detects
these automatically in any photo/scan of a filled-in sheet (and can tell
the orientation even if the photo is upside-down), so no manual
calibration step is needed for sheets produced by this script. Because
the bubble grid is generated from the same coordinates used to draw the
sheet, layout.json is exact from the start.

Usage:
    python tools/generate_answer_sheet.py
    python tools/generate_answer_sheet.py --config config.json --layout-out layout.json

Outputs (by default, into the project root):
    answer_sheet.pdf   - print this (A4, 300 DPI)
    answer_sheet.png   - quick-look preview of the same sheet
    layout.json        - bubble + fiducial marker coordinates for main.py

Re-run this any time you change num_questions/options in config.json, and
re-print - no manual re-calibration needed since the layout is exact.
"""

import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DPI = 300
SUPERSAMPLE = 3                    # anti-aliasing factor while drawing
CANVAS_W, CANVAS_H = 2480, 3508    # A4 @ 300 DPI

MARKER_INSET = 95                  # canonical px from page edge to marker center
MARKER_SQUARE = 74                 # side length of the 3 square markers
MARKER_CIRCLE_R = 38               # radius of the TL circle marker (orientation key)

CONTENT_LEFT = MARKER_INSET * 2 + 10
CONTENT_RIGHT = CANVAS_W - 1 - (MARKER_INSET * 2 + 10)
CONTENT_W = CONTENT_RIGHT - CONTENT_LEFT

GRID_TOP = 700
GRID_BOTTOM = 3230
FOOTER_Y = 3280

BUBBLE_RADIUS = 24
OPT_GAP = 66
LABEL_W = 66


def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def marker_centers():
    """The 4 fiducial marker centers in canonical (print) coordinates."""
    return {
        "TL": (float(MARKER_INSET), float(MARKER_INSET)),
        "TR": (float(CANVAS_W - 1 - MARKER_INSET), float(MARKER_INSET)),
        "BR": (float(CANVAS_W - 1 - MARKER_INSET), float(CANVAS_H - 1 - MARKER_INSET)),
        "BL": (float(MARKER_INSET), float(CANVAS_H - 1 - MARKER_INSET)),
    }


def build_bubble_layout(num_blocks, rows_per_block, questions_per_block, options):
    block_w = CONTENT_W / num_blocks
    row_ys = np.linspace(GRID_TOP + 40, GRID_BOTTOM - 40, rows_per_block)

    bubbles = {}
    for b in range(num_blocks):
        block_x0 = CONTENT_LEFT + b * block_w + LABEL_W
        for r in range(rows_per_block):
            q_num = b * questions_per_block + r + 1
            y = float(row_ys[r])
            bubbles[str(q_num)] = {
                opt: [float(block_x0 + i * OPT_GAP), y]
                for i, opt in enumerate(options)
            }
    return bubbles


def draw_sheet(bubbles, sheet_title, num_blocks, rows_per_block, options):
    W, H = CANVAS_W * SUPERSAMPLE, CANVAS_H * SUPERSAMPLE
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def sx(v):
        return v * SUPERSAMPLE

    # Outer border frame
    frame_pad = sx(60)
    d.rectangle([frame_pad, frame_pad, W - frame_pad, H - frame_pad],
                outline=(20, 20, 20), width=int(sx(2.2)))
    d.rectangle([frame_pad + sx(10), frame_pad + sx(10), W - frame_pad - sx(10), H - frame_pad - sx(10)],
                outline=(150, 150, 150), width=int(sx(1)))

    # Fiducial markers: circle = true TL (orientation key), squares = TR/BR/BL
    for key, (cx, cy) in marker_centers().items():
        cx, cy = sx(cx), sx(cy)
        if key == "TL":
            r = sx(MARKER_CIRCLE_R)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(10, 10, 10))
        else:
            s = sx(MARKER_SQUARE) / 2
            d.rectangle([cx - s, cy - s, cx + s, cy + s], fill=(10, 10, 10))

    # Title bar
    bar_top, bar_bot = sx(140), sx(230)
    d.rectangle([sx(CONTENT_LEFT - 40), bar_top, sx(CONTENT_RIGHT + 40), bar_bot], fill=(25, 25, 25))
    f_title = _font(int(sx(30)), bold=True)
    tw = d.textlength(sheet_title, font=f_title)
    d.text(((W - tw) / 2, (bar_top + bar_bot) / 2 - sx(20)), sheet_title, font=f_title, fill="white")

    # Candidate info fields
    info_y = sx(270)
    f_label = _font(int(sx(20)), bold=True)
    fields = [
        ("Candidate Name:", CONTENT_LEFT, CONTENT_LEFT + 620),
        ("Roll No:", CONTENT_LEFT + 700, CONTENT_LEFT + 1000),
        ("Date:", CONTENT_LEFT + 1080, CONTENT_LEFT + 1320),
    ]
    for label, x0, x1 in fields:
        d.text((sx(x0), info_y), label, font=f_label, fill=(20, 20, 20))
        lx0 = sx(x0) + d.textlength(label, font=f_label) + sx(12)
        d.line([lx0, info_y + sx(30), sx(x1), info_y + sx(30)], fill=(20, 20, 20), width=int(sx(1.6)))

    # Instructions box
    ibox_y0, ibox_y1 = sx(340), sx(460)
    d.rectangle([sx(CONTENT_LEFT), ibox_y0, sx(CONTENT_RIGHT), ibox_y1], outline=(20, 20, 20), width=int(sx(1.4)))
    f_instr_h = _font(int(sx(18)), bold=True)
    f_instr = _font(int(sx(16)))
    d.text((sx(CONTENT_LEFT + 16), ibox_y0 + sx(8)), "Instructions", font=f_instr_h, fill=(20, 20, 20))
    instr_lines = [
        "Use only a black/blue ball-point pen or HB pencil. Darken the bubble completely, do not tick or cross.",
        "Do not fold, crease, or staple this sheet. Keep the four corner registration marks fully visible and unmarked.",
        "Erasing is not recommended; a clean single mark per question is required. Multiple marks void that answer.",
    ]
    for i, line in enumerate(instr_lines):
        d.text((sx(CONTENT_LEFT + 16), ibox_y0 + sx(34) + i * sx(24)), line, font=f_instr, fill=(40, 40, 40))

    # Grid column headers
    block_w = CONTENT_W / num_blocks
    f_hdr = _font(int(sx(18)), bold=True)
    f_qnum = _font(int(sx(17)), bold=True)
    f_opt = _font(int(sx(13)))

    for b in range(num_blocks):
        block_x0 = CONTENT_LEFT + b * block_w + LABEL_W
        hy = sx(GRID_TOP - 30)
        d.text((sx(block_x0 - LABEL_W + 10), hy), "Q#", font=f_hdr, fill=(20, 20, 20))
        for i, opt in enumerate(options):
            ox = sx(block_x0 + i * OPT_GAP)
            tw2 = d.textlength(opt, font=f_hdr)
            d.text((ox - tw2 / 2, hy), opt, font=f_hdr, fill=(20, 20, 20))
        d.line([sx(block_x0 - LABEL_W), sx(GRID_TOP - 4), sx(block_x0 - LABEL_W + block_w - 30), sx(GRID_TOP - 4)],
               fill=(120, 120, 120), width=int(sx(1)))

    # Subtle alternating row-group guide lines (every 5 rows)
    row_ys = np.linspace(GRID_TOP + 40, GRID_BOTTOM - 40, rows_per_block)
    for r in range(rows_per_block):
        if r % 5 == 4 and r != rows_per_block - 1:
            y = row_ys[r]
            d.line([sx(CONTENT_LEFT), sx(y) + sx(22), sx(CONTENT_RIGHT), sx(y) + sx(22)],
                   fill=(225, 225, 225), width=int(sx(1)))

    # Question numbers + bubbles
    for q_str, opts in bubbles.items():
        q_num = int(q_str)
        ax, ay = opts[options[0]]
        d.text((sx(ax - LABEL_W + 6), sx(ay) - sx(11)), str(q_num), font=f_qnum, fill=(20, 20, 20))
        for opt, (x, y) in opts.items():
            x, y, rad = sx(x), sx(y), sx(BUBBLE_RADIUS)
            d.ellipse([x - rad, y - rad, x + rad, y + rad], outline=(15, 15, 15), width=int(sx(2.2)))
            tw3 = d.textlength(opt, font=f_opt)
            d.text((x - tw3 / 2, y - sx(8)), opt, font=f_opt, fill=(190, 190, 190))

    # Footer
    f_foot = _font(int(sx(15)))
    foot_text = "This sheet is machine-scored. Keep corner marks clean. Contact the exam cell for a replacement if damaged."
    d.text((sx(CONTENT_LEFT), sx(FOOTER_Y)), foot_text, font=f_foot, fill=(90, 90, 90))

    return img.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description="Generate the print-ready, auto-calibrating OMR answer sheet")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--pdf-out", default="answer_sheet.pdf")
    parser.add_argument("--png-out", default="answer_sheet.png")
    parser.add_argument("--layout-out", default="layout.json")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    num_blocks = config["num_blocks"]
    rows_per_block = config["rows_per_block"]
    questions_per_block = config["questions_per_block"]
    options = config["options"]
    sheet_title = f'{config["sheet_title"]}'

    bubbles = build_bubble_layout(num_blocks, rows_per_block, questions_per_block, options)
    img = draw_sheet(bubbles, sheet_title, num_blocks, rows_per_block, options)

    img.save(args.png_out, dpi=(DPI, DPI))
    img.save(args.pdf_out, "PDF", resolution=DPI)

    layout = {
        "canonical_width": CANVAS_W,
        "canonical_height": CANVAS_H,
        "bubble_radius": BUBBLE_RADIUS,
        "fiducial_markers": {k: list(v) for k, v in marker_centers().items()},
        "bubbles": bubbles,
    }
    with open(args.layout_out, "w") as f:
        json.dump(layout, f, indent=2)

    print(f"Saved {args.pdf_out}, {args.png_out}, and {args.layout_out} "
          f"({len(bubbles)} questions x {len(options)} options).")


if __name__ == "__main__":
    main()
