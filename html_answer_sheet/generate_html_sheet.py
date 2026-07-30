"""
Generates a print-ready, A4, 300-DPI-optimized OMR answer sheet as
separate HTML + CSS files, from a single CONFIG block below.

No JavaScript, no external dependencies - open the HTML in any browser
and print (Ctrl/Cmd+P) at 100% scale, "Actual size", no margins added by
the browser (the @page rule already defines the exact print margins).

Re-run this script after editing CONFIG to regenerate both files.
"""
import os

# --------------------------------------------------------------------
# CONFIGURABLE VARIABLES  (section 13 of the spec)
# --------------------------------------------------------------------
CONFIG = {
    "num_questions": 100,
    "options": ["A", "B", "C", "D"],
    "num_columns": 4,              # question columns (100/4 = 25 rows each)
    "roll_digits": 6,

    "school_name": "DIVINE LIGHT CENTRAL SCHOOL",
    "school_address": "SHIVPURI, RAMCHANDRAPUR, BIHARSHARIF (NALANDA)",
    "school_recognition": "Recognized by Government of Bihar under R.T.E. 2009",
    "school_contact": "Web: divinelightcentralschool.com &nbsp;|&nbsp; Ph No: 8340220267",
    "logo_file": "school_logo.png",   # image file, same folder as the HTML
}

QUESTIONS_PER_COL = CONFIG["num_questions"] // CONFIG["num_columns"]
OPTIONS = CONFIG["options"]
ROLL_DIGITS = CONFIG["roll_digits"]

# --------------------------------------------------------------------
# GEOMETRY (all explicit, computed in mm - deliberately NOT relying on
# CSS flex-grow to fill remaining vertical space: that was tried first
# and rendered unpredictably across engines, so every section height
# here is a fixed number and they are checked to sum exactly to the
# available content height => guaranteed single A4 page, no overflow).
# --------------------------------------------------------------------
PAGE_MARGIN = 3        # mm, outer page margin
MARKER = 6             # mm, primary corner registration square size
FRAME_GAP = 2          # mm, gap between marker frame and content
CONTENT_H = 297 - 2 * (PAGE_MARGIN + MARKER + FRAME_GAP)   # 275mm
CONTENT_W = 210 - 2 * (PAGE_MARGIN + MARKER + FRAME_GAP)   # 188mm

HEADER_H = 17          # 4-line school letterhead (name/address/recognition/contact)
TITLEBAR_H = 5
BOTTOM_H = 17
SECTION_GAP = 0.6      # margin-top between each of the 5 stacked blocks (4 gaps)
# (instructions block removed per feedback - one less block, one less gap)

# Bubbles are printed 30% smaller (radius, so also 30% smaller diameter)
# than the original 5mm spec size - real scans showed hand-filled ink
# frequently drifting several pixels off a bubble's exact printed
# center, and shrinking the circle itself (while keeping row/column
# PITCH unchanged - see ROLL_ROW_H below) opens up more clear paper
# between neighboring bubbles, which is exactly what makes that drift
# tolerable to detect instead of bleeding into the wrong bubble.
BUBBLE_SCALE = 0.7
BASE_BUBBLE_D = 5.0    # mm - original spec diameter; row/column PITCH is
                       # still sized off this base value (see below), so
                       # shrinking the printed circle doesn't change the
                       # sheet's overall geometry/page height at all -
                       # it just adds breathing room around each bubble.

ROLL_BUBBLE_D = BASE_BUBBLE_D * BUBBLE_SCALE   # mm - printed roll-bubble diameter
ROLL_TITLE_H = 3.5
ROLL_DIGITBOX_H = 7.0  # write-in box for each roll digit (made larger per feedback)
ROLL_DIGITBOX_MARGIN = 1.0
ROLL_ROW_GAP = 0.15
# Row pitch is deliberately sized off BASE_BUBBLE_D (the pre-shrink
# diameter), not the smaller ROLL_BUBBLE_D actually drawn - this is what
# turns "smaller bubble" into "more gap around the bubble" instead of
# just uniformly shrinking everything (which would leave the crowding
# between rows exactly as tight as before, just at a smaller scale).
ROLL_ROW_H = BASE_BUBBLE_D + ROLL_ROW_GAP
ROLL_GRID_VPADDING = 1.0   # .roll-grid CSS padding, top+bottom (mm, each side)
ROLL_GRID_BORDER = 0.3     # .roll-grid CSS border width (mm, each side)
# NOTE: .roll-grid's own padding+border must be added on top of its inner
# content sum, or the box is too short for its content and the roll grid
# bleeds down into the question grid below it (this caused the overlap
# bug reported after the previous revision - the fix is these two lines):
_roll_inner_h = ROLL_TITLE_H + ROLL_DIGITBOX_H + ROLL_DIGITBOX_MARGIN + 10 * ROLL_ROW_H
INFO_ROLL_H = _roll_inner_h + 2 * ROLL_GRID_VPADDING + 2 * ROLL_GRID_BORDER

ROLL_GRID_W = 74       # mm, fixed compact width, right-anchored (not flex-proportional)

QGRID_HEADER_H = 4
QGRID_BORDER_PAD = 1.8  # border-top + padding-top

_fixed_sum = HEADER_H + TITLEBAR_H + INFO_ROLL_H + BOTTOM_H + SECTION_GAP * 4
QGRID_H = CONTENT_H - _fixed_sum
QGRID_BODY_H = QGRID_H - QGRID_HEADER_H - QGRID_BORDER_PAD
# Q_ROW_H (the question grid's row pitch) is already independent of the
# bubble's own diameter - it's just the available body height divided
# across 25 rows - so shrinking BUBBLE_D below directly opens up more
# gap around each bubble here too, the same way it does for the roll
# grid above.
Q_ROW_H = QGRID_BODY_H / QUESTIONS_PER_COL
BUBBLE_D = BASE_BUBBLE_D * BUBBLE_SCALE   # mm - printed answer-bubble diameter

assert Q_ROW_H >= BUBBLE_D, f"question row pitch {Q_ROW_H:.2f}mm is smaller than the bubble diameter - would overlap"
assert ROLL_ROW_H >= ROLL_BUBBLE_D, "roll grid row pitch smaller than bubble diameter - would overlap"


# --------------------------------------------------------------------
# HTML fragment builders
# --------------------------------------------------------------------
def build_ticks(count, vertical=False):
    cls = "tick tick-v" if vertical else "tick"
    return "".join(f'<span class="{cls}"></span>' for _ in range(count))


def _ci_field(label):
    return f'<div class="ci-field"><span class="ci-label">{label}</span><span class="ci-line"></span></div>'


def _ci_row(*labels):
    # 1 label = spans the full row width (its lone flex:1 child stretches
    # to fill); 2 labels = the usual side-by-side pair. Same row/field
    # CSS either way - no geometry/height change, just field grouping.
    return '<div class="ci-row">' + "".join(_ci_field(l) for l in labels) + '</div>'


def build_candidate_info():
    # Student Name on its own full-width row; Class + Section combined
    # into one field; Student/Invigilator Signature kept as the last
    # (bottom) row - per feedback. Still 4 rows total, so the box's
    # fixed height (unchanged) distributes the same as before.
    rows = [
        _ci_row("Student Name"),
        _ci_row("Class / Section", "Admission Number"),
        _ci_row("Subject", "Exam Date"),
        _ci_row("Student Signature", "Invigilator Signature"),
    ]
    return "\n".join(rows)


def build_roll_grid(digits):
    # digit entry boxes (student hand-writes the roll number here)
    boxes = "".join('<div class="roll-digit-box"></div>' for _ in range(digits))

    # bubble matrix: one column per digit position, one row per value 0-9
    body_rows = []
    for value in range(10):
        cells = "".join(
            f'<div class="rb-cell"><span class="bubble" data-v="{value}"></span></div>'
            for _ in range(digits)
        )
        body_rows.append(f'<div class="rb-row"><div class="rb-cell rb-rowlabel">{value}</div>{cells}</div>')

    return f"""
    <div class="roll-title">Roll Number</div>
    <div class="roll-digit-boxes">{boxes}</div>
    <div class="roll-bubble-grid">
      {''.join(body_rows)}
    </div>
    """


def build_question_columns(num_questions, num_columns, options):
    per_col = num_questions // num_columns
    cols_html = []
    for c in range(num_columns):
        start = c * per_col + 1
        rows_html = []
        header_opts = "".join(f'<span class="qh-opt">{o}</span>' for o in options)
        rows_html.append(f'<div class="q-row q-headrow"><span class="q-num"></span>{header_opts}</div>')
        for q in range(start, start + per_col):
            # Option letter is rendered INSIDE the bubble itself (centered
            # text), not as a separate label beside it.
            opts_html = "".join(
                f'<span class="opt"><span class="bubble" data-opt="{o}">{o}</span></span>'
                for o in options
            )
            rows_html.append(f'<div class="q-row"><span class="q-num">{q}</span>{opts_html}</div>')
        cols_html.append(f'<div class="q-col">{"".join(rows_html)}</div>')
    return "".join(cols_html)


def build_html():
    ticks_h = build_ticks(14)
    ticks_v = build_ticks(9, vertical=True)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OMR Answer Sheet - {CONFIG['num_questions']} Questions</title>
<link rel="stylesheet" href="omr_sheet.css">
</head>
<body>
<div class="sheet">

  <!-- ============ Primary OMR registration marks (corners) ============ -->
  <div class="marker marker-tl" aria-hidden="true"></div>
  <div class="marker marker-tr" aria-hidden="true"></div>
  <div class="marker marker-bl" aria-hidden="true"></div>
  <div class="marker marker-br" aria-hidden="true"></div>

  <!-- ============ Secondary alignment marks (scanner skew/scale calibration) ============ -->
  <div class="ticks ticks-top" aria-hidden="true">{ticks_h}</div>
  <div class="ticks ticks-bottom" aria-hidden="true">{ticks_h}</div>
  <div class="ticks ticks-left" aria-hidden="true">{ticks_v}</div>
  <div class="ticks ticks-right" aria-hidden="true">{ticks_v}</div>

  <div class="content">

    <!-- ============ School header / letterhead ============ -->
    <header class="sheet-header">
      <img class="logo-box" src="{CONFIG['logo_file']}" alt="School Logo">
      <div class="school-info">
        <div class="school-name">{CONFIG['school_name']}</div>
        <div class="school-address">{CONFIG['school_address']}</div>
        <div class="school-recognition">{CONFIG['school_recognition']}</div>
        <div class="school-contact">{CONFIG['school_contact']}</div>
      </div>
    </header>

    <div class="title-bar">OMR ANSWER SHEET</div>

    <!-- ============ Candidate info + Roll number grid ============ -->
    <section class="info-roll-band">
      <div class="candidate-info">
        {build_candidate_info()}
      </div>
      <div class="roll-grid">
        {build_roll_grid(ROLL_DIGITS)}
      </div>
    </section>

    <!-- ============ Question answer grid ============ -->
    <section class="question-grid">
      {build_question_columns(CONFIG['num_questions'], CONFIG['num_columns'], OPTIONS)}
    </section>

    <!-- ============ Declaration + Invigilator ============ -->
    <section class="bottom-band">
      <div class="declaration">
        <p>I hereby declare that the information provided above is correct and that I have followed all examination instructions.</p>
        <div class="sig-row">
          <span class="ci-label">Student Signature</span><span class="ci-line short"></span>
          <span class="ci-label">Date</span><span class="ci-line short"></span>
        </div>
      </div>
      <div class="invigilator">
        <div class="section-title">Invigilator Use Only</div>
        <div class="inv-row"><span class="ci-label">Verified By</span><span class="ci-line short"></span></div>
        <div class="inv-row"><span class="ci-label">Invigilator Signature</span><span class="ci-line short"></span></div>
        <div class="inv-row attendance">
          <span class="ci-label">Room No.</span><span class="ci-line short"></span>
          <span class="checkbox"></span> Present &nbsp;
          <span class="checkbox"></span> Absent
        </div>
      </div>
    </section>

  </div>
</div>
</body>
</html>
"""
    return html


CSS = r"""
/* ==================================================================
   OMR Answer Sheet - print stylesheet
   A4, 300-DPI-optimized, black & white, all measurements in mm.
   ================================================================== */

:root {
  --page-w: 210mm;
  --page-h: 297mm;
  --page-margin: @@PAGE_MARGIN@@mm;

  --ink: #000;
  --line: #000;
  --muted: #555;

  --marker-size: @@MARKER@@mm;   /* primary corner registration squares */
  --frame-gap: @@FRAME_GAP@@mm;
  --tick-w: 1mm;
  --tick-h: 3mm;

  --bubble-d: @@BUBBLE_D@@mm;         /* answer bubble diameter (spec: 5-6mm) */
  --bubble-border: 0.35mm;
  --roll-bubble-d: @@ROLL_BUBBLE_D@@mm;

  /* explicit, pre-computed section heights (see GEOMETRY block in the
     generator script) - the whole vertical stack is fixed-height by
     design so the sheet is guaranteed to fit exactly one A4 page */
  --header-h: @@HEADER_H@@mm;
  --titlebar-h: @@TITLEBAR_H@@mm;
  --section-gap: @@SECTION_GAP@@mm;
  --roll-title-h: @@ROLL_TITLE_H@@mm;
  --roll-digitbox-h: @@ROLL_DIGITBOX_H@@mm;
  --roll-digitbox-margin: @@ROLL_DIGITBOX_MARGIN@@mm;
  --rb-row-h: @@ROLL_ROW_H@@mm;
  --qgrid-h: @@QGRID_H@@mm;
  --qgrid-header-h: @@QGRID_HEADER_H@@mm;
  --q-row-h: @@Q_ROW_H@@mm;
  --bottom-h: @@BOTTOM_H@@mm;
  --roll-grid-w: @@ROLL_GRID_W@@mm;
  --info-roll-h: @@INFO_ROLL_H@@mm;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  font-family: "DejaVu Sans", Arial, Helvetica, sans-serif;
  color: var(--ink);
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

@page {
  size: A4 portrait;
  margin: 0; /* we manage all spacing ourselves via .sheet, for exact mm control */
}

/* Prevents any accidental second page: everything must fit inside .sheet */
.sheet {
  position: relative;
  width: var(--page-w);
  height: var(--page-h);
  padding: var(--page-margin);
  overflow: hidden;
  page-break-after: avoid;
  page-break-inside: avoid;
}

/* ---------------- Primary registration markers ---------------- */
.marker {
  position: absolute;
  width: var(--marker-size);
  height: var(--marker-size);
  background: var(--ink);
}
.marker-tl { top: var(--page-margin); left: var(--page-margin); }
.marker-tr { top: var(--page-margin); right: var(--page-margin); }
.marker-bl { bottom: var(--page-margin); left: var(--page-margin); }
.marker-br { bottom: var(--page-margin); right: var(--page-margin); }

/* ---------------- Secondary alignment ticks ---------------- */
.ticks {
  position: absolute;
  display: flex;
  justify-content: space-between;
  pointer-events: none;
}
.ticks-top, .ticks-bottom {
  left: calc(var(--page-margin) + var(--marker-size) + 2mm);
  right: calc(var(--page-margin) + var(--marker-size) + 2mm);
  height: var(--tick-h);
}
.ticks-top { top: var(--page-margin); }
.ticks-bottom { bottom: var(--page-margin); }
.tick { width: var(--tick-w); height: var(--tick-h); background: var(--ink); }

.ticks-left, .ticks-right {
  top: calc(var(--page-margin) + var(--marker-size) + 2mm);
  bottom: calc(var(--page-margin) + var(--marker-size) + 2mm);
  width: var(--tick-h);
  flex-direction: column;
}
.ticks-left { left: var(--page-margin); }
.ticks-right { right: var(--page-margin); }
.tick-v { width: var(--tick-h); height: var(--tick-w); background: var(--ink); }

/* ---------------- Content wrapper (inside the marker frame) ---------------- */
.content {
  position: absolute;
  top: calc(var(--page-margin) + var(--marker-size) + var(--frame-gap));
  left: calc(var(--page-margin) + var(--marker-size) + var(--frame-gap));
  right: calc(var(--page-margin) + var(--marker-size) + var(--frame-gap));
  bottom: calc(var(--page-margin) + var(--marker-size) + var(--frame-gap));
  display: flex;
  flex-direction: column;
}
.content > * + * { margin-top: var(--section-gap); }

/* ---------------- Header ---------------- */
.sheet-header {
  display: flex;
  align-items: center;
  gap: 6mm;
  height: var(--header-h);
  flex: 0 0 auto;
}
.logo-box {
  width: var(--header-h);
  height: var(--header-h);
  object-fit: contain;
  flex-shrink: 0;
}
.school-info { flex: 1; text-align: left; }
.school-name {
  font-family: "Georgia", "DejaVu Serif", serif;
  font-size: 14.5pt;
  font-weight: bold;
  letter-spacing: 0.3mm;
  line-height: 1.15;
}
.school-address {
  font-size: 7.6pt;
  font-weight: bold;
  margin-top: 0.5mm;
  line-height: 1.15;
}
.school-recognition {
  font-size: 7pt;
  margin-top: 0.4mm;
  line-height: 1.15;
}
.school-contact {
  font-size: 7pt;
  margin-top: 0.4mm;
  line-height: 1.15;
}

.title-bar {
  height: var(--titlebar-h);
  flex: 0 0 auto;
  border-top: 0.5mm solid var(--ink);
  border-bottom: 0.5mm solid var(--ink);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10pt;
  font-weight: bold;
  letter-spacing: 0.8mm;
}

/* ---------------- Candidate info + Roll grid band ---------------- */
.info-roll-band {
  display: flex;
  align-items: stretch;
  gap: 3mm;
  height: var(--info-roll-h);
  flex: 0 0 auto;
}
.candidate-info {
  flex: 1;              /* takes all width the fixed-width roll-grid doesn't need */
  border: 0.3mm solid var(--ink);
  padding: 1.5mm 2.5mm;
  display: flex;
  flex-direction: column;
  justify-content: space-evenly;
}
.ci-row { display: flex; gap: 3mm; }
.ci-field { flex: 1; display: flex; align-items: flex-end; gap: 1.5mm; }
.ci-label { font-size: 7.3pt; white-space: nowrap; }
.ci-line { flex: 1; border-bottom: 0.25mm solid var(--ink); height: 3.6mm; }
.ci-line.short { flex: 0 0 22mm; }

.roll-grid {
  flex: 0 0 var(--roll-grid-w);  /* fixed, compact width - right-anchored, not proportional */
  border: 0.3mm solid var(--ink);
  padding: 1mm 2mm;
  display: flex;
  flex-direction: column;
}
.roll-title { height: var(--roll-title-h); font-size: 7.5pt; font-weight: bold; text-align: center; }
.roll-digit-boxes {
  display: grid;
  grid-template-columns: repeat(@@ROLL_DIGITS@@, 1fr);
  gap: 0.6mm;
  height: var(--roll-digitbox-h);
  margin-bottom: var(--roll-digitbox-margin);
}
.roll-digit-box {
  height: 100%;
  border: 0.25mm solid var(--ink);
}
.roll-bubble-grid { display: flex; flex-direction: column; }
.rb-row { display: grid; grid-template-columns: 3mm repeat(@@ROLL_DIGITS@@, 1fr); align-items: center; height: var(--rb-row-h); }
.rb-cell { display: flex; align-items: center; justify-content: center; }
.rb-rowlabel { font-size: 6.5pt; font-weight: bold; }
.rb-cell .bubble { width: var(--roll-bubble-d); height: var(--roll-bubble-d); font-size: 0; }

/* ---------------- Bubbles (shared) - option letter is centered INSIDE ---------------- */
/* NOTE: must be `flex`, not `inline-flex` - WeasyPrint (and some other
   engines) double-paint the border on inline-flex + border-radius:50%
   elements (renders as a faint ghosted second circle offset up-left).
   `.bubble` is always the sole child of an already-centering flex
   parent (.opt / .rb-cell), so it never needed to be inline. */
.bubble {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--bubble-d);
  height: var(--bubble-d);
  border: var(--bubble-border) solid var(--ink);
  border-radius: 50%;
  background: #fff;
  font-size: 6.5pt;
  color: #666;
  line-height: 1;
}

/* ---------------- Question grid ---------------- */
.question-grid {
  display: flex;
  gap: 2.5mm;
  height: var(--qgrid-h);
  flex: 0 0 auto;
  border-top: 0.3mm solid var(--ink);
  padding-top: 1.5mm;
}
.q-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-left: 0.2mm solid #bbb;
  padding-left: 2mm;
}
.q-col:first-child { border-left: none; padding-left: 0; }
.q-row {
  height: var(--q-row-h);
  flex: 0 0 auto;
  display: flex;
  align-items: center;
}
.q-headrow { height: var(--qgrid-header-h); border-bottom: 0.25mm solid var(--ink); margin-bottom: 0.6mm; font-weight: bold; }
.q-num { width: 7mm; font-size: 8pt; font-weight: bold; flex-shrink: 0; }
.qh-opt { flex: 1; text-align: center; font-size: 8pt; }
.opt { flex: 1; display: flex; align-items: center; justify-content: center; }

.section-title { font-size: 7pt; font-weight: bold; margin-bottom: 0.5mm; }

/* ---------------- Declaration + Invigilator ---------------- */
.bottom-band {
  display: flex;
  gap: 4mm;
  height: var(--bottom-h);
  flex: 0 0 auto;
  border-top: 0.3mm solid var(--ink);
  padding-top: 1mm;
  overflow: hidden;
}
.declaration { flex: 1.5; font-size: 6.8pt; line-height: 1.2; }
.declaration p { margin: 0 0 0.8mm 0; }
.sig-row { display: flex; align-items: flex-end; gap: 2mm; margin-top: 1mm; }
.invigilator { flex: 1; font-size: 6.8pt; line-height: 1.2; }
.inv-row { display: flex; align-items: flex-end; gap: 1.2mm; margin-top: 0.6mm; }
.attendance { align-items: center; }
.checkbox {
  display: inline-block;
  width: 3mm;
  height: 3mm;
  border: 0.25mm solid var(--ink);
}
"""


def build_css():
    tokens = {
        "PAGE_MARGIN": PAGE_MARGIN, "MARKER": MARKER, "FRAME_GAP": FRAME_GAP,
        "BUBBLE_D": BUBBLE_D, "ROLL_BUBBLE_D": ROLL_BUBBLE_D,
        "HEADER_H": HEADER_H, "TITLEBAR_H": TITLEBAR_H, "SECTION_GAP": SECTION_GAP,
        "ROLL_TITLE_H": ROLL_TITLE_H, "ROLL_DIGITBOX_H": ROLL_DIGITBOX_H,
        "ROLL_DIGITBOX_MARGIN": ROLL_DIGITBOX_MARGIN, "ROLL_ROW_H": ROLL_ROW_H,
        "QGRID_H": QGRID_H, "QGRID_HEADER_H": QGRID_HEADER_H, "Q_ROW_H": Q_ROW_H,
        "BOTTOM_H": BOTTOM_H, "INFO_ROLL_H": INFO_ROLL_H, "ROLL_GRID_W": ROLL_GRID_W,
        "ROLL_DIGITS": ROLL_DIGITS,
    }
    css = CSS
    for name, value in tokens.items():
        css = css.replace(f"@@{name}@@", f"{value:.3f}".rstrip("0").rstrip("."))
    assert "@@" not in css, "unresolved CSS placeholder token remains"
    return css


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    html = build_html()
    css = build_css()
    with open(os.path.join(out_dir, "omr_sheet.html"), "w") as f:
        f.write(html)
    with open(os.path.join(out_dir, "omr_sheet.css"), "w") as f:
        f.write(css)
    print(f"Wrote omr_sheet.html and omr_sheet.css  "
          f"(bubble diameter: {BUBBLE_D:.2f}mm [{BUBBLE_SCALE:.0%} of the {BASE_BUBBLE_D:.1f}mm base], "
          f"question row pitch: {Q_ROW_H:.2f}mm, roll row pitch: {ROLL_ROW_H:.2f}mm, "
          f"content area: {CONTENT_W:.0f}x{CONTENT_H:.0f}mm)")


if __name__ == "__main__":
    main()
