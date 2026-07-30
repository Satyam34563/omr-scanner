# 100-Question OMR Answer Sheet (HTML/CSS, print-ready)

`omr_sheet.html` + `omr_sheet.css` are a self-contained, print-optimized
OMR answer sheet for Divine Light Central School: A4 portrait, black &
white, 100 questions (4 options each, letter shown inside each bubble)
across 4 columns of 25, a 6-digit roll number bubble grid (right-aligned,
compact), candidate info fields, a declaration, and an invigilator
section. `omr_sheet.pdf` is a ready-to-print render of the same file.
`school_logo.png` is the crest referenced by the header - keep it in
this folder alongside the HTML.

## Printing

Open `omr_sheet.html` in a browser and print (Ctrl/Cmd+P):
- Paper size: A4
- Margins: **None** (the page already defines its own exact margins)
- Scale: **100% / Actual size** (do not use "Fit to page")

Or just print `omr_sheet.pdf` directly - it was rendered from the same
HTML/CSS at 100% scale. The school name renders in Georgia where
available (falls back to a serif system font otherwise).

## Reconfiguring

Edit the `CONFIG` dict at the top of `generate_html_sheet.py` (school
name, address, recognition line, contact line, logo file, number of
roll digits) then re-run:

```bash
python3 generate_html_sheet.py
```

This regenerates both `omr_sheet.html` and `omr_sheet.css`. Changing
`num_questions` or `num_columns` is also supported, but note the script
asserts that the resulting per-row bubble spacing doesn't shrink below
the bubble diameter (it will raise an error rather than silently
producing an overlapping/unscannable layout) - if that happens, trim
`INSTRUCTIONS_H` / `BOTTOM_H` / `HEADER_H` in the GEOMETRY block.

To swap the logo, replace `school_logo.png` (or point `logo_file` in
CONFIG at a different filename in this same folder).

## Design notes

- All section heights are pre-computed in mm (see the GEOMETRY block
  near the top of `generate_html_sheet.py`) and asserted to sum to
  exactly the A4 content area - the page is guaranteed to fit on one
  sheet with no page breaks, rather than relying on CSS flexbox to
  "fill remaining space" (which rendered inconsistently across engines
  during development).
- 4 solid black squares at the corners are the primary OMR registration
  marks; small tick marks along all 4 edges are secondary alignment
  marks for scanner skew/scale correction.
- Answer bubbles are 3.5mm diameter (70% of the original 5mm spec size,
  shrunk to give more breathing room around each mark) with a ~6.5mm
  row pitch, deliberately still sized off the original 5mm base value -
  a clean, comfortable gap with no overlap risk. Roll-number bubbles
  are the same 3.5mm diameter with a tighter (but still non-overlapping)
  ~5.15mm pitch, since that grid always has 10 rows (digits 0-9)
  regardless of how many roll digits are configured. `BUBBLE_SCALE` in
  the GEOMETRY block controls this - change it and re-run
  `generate_html_sheet.py`, then re-run
  `tools/auto_generate_layout.py` to recalibrate `layout.json` to match
  (its `BUBBLE_DIAMETER_MM` constant must be kept in sync with this
  script's `BASE_BUBBLE_D * BUBBLE_SCALE`).
- The roll-number grid has a fixed, compact width (`ROLL_GRID_W` in the
  GEOMETRY block) and sits flush against the right edge of its row;
  the candidate-info box takes all the remaining width, so it grows or
  shrinks automatically if `ROLL_GRID_W` or `roll_digits` changes.
- A previous revision had a bug where the roll-number box's own
  padding/border weren't counted in its height budget, so it silently
  overflowed a couple mm into the question grid below it. Fixed by
  adding `ROLL_GRID_VPADDING`/`ROLL_GRID_BORDER` into `INFO_ROLL_H` in
  the GEOMETRY block - worth keeping in mind if you add padding/borders
  to any other bordered box: its full box height (including padding
  and border) has to be counted, not just the height of what's inside it.
- No JavaScript. Plain semantic HTML, CSS Grid/Flexbox for layout.
