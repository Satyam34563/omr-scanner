# OMR Checker

Automatically grades scanned/photographed copies of the "Divine Light
Central School" 100-question OMR answer sheet
(`html_answer_sheet/omr_sheet.pdf`). Give it one combined PDF of the
whole batch's scans (e.g. straight off a scanner's "scan to PDF"
feature) and an Excel answer key; it hands back a batch Excel report
and a single letterhead-branded PDF containing every student's result,
one after another, with every question marked correct/incorrect.

Calibration is **fully automatic** - the sheet prints 4 solid
registration squares near its corners specifically so the tool can
figure out bubble positions on its own, from any scan or photo, with
no manual clicking step at all.

## How it works

1. **Master layout (one-time, automatic)** - `tools/auto_generate_layout.py`
   renders the clean master PDF and detects every marker and bubble on
   it programmatically (contour/shape analysis - no clicking), saving
   `layout.json`. Re-run only if the sheet template itself changes.
2. **Reading the batch** - `input/scans.pdf` (one page per filled-in
   sheet) is rasterized page by page. For each page, the 4 corner
   markers are detected and used to perspective-correct the image so
   it lines up pixel-for-pixel with `layout.json`, regardless of how
   that page was scanned, rotated, or scaled.
3. **Detection** - for every one of the 100 questions, the tool
   measures how dark each of its A/B/C/D bubbles is; every bubble at
   or above the fill threshold is selected, so a question can have
   more than one shaded answer (e.g. `["C", "D"]"`), not just a single
   pick. Roll-number digits are different - each position can only
   hold one value, so there it still picks the single darkest bubble
   and flags a position if two values are shaded similarly dark.
4. **Roll number validation** - the bubbled roll number is looked up
   against the school's own student records
   (`dlcs.managemyschools.in`). If it resolves, the student's id_no,
   name, father's name, class, and section are pulled in for the
   report. If a digit couldn't be read cleanly, OR the roll number
   doesn't match any real student, the sheet is set aside for manual
   review instead of being guessed at - see "Roll number verification"
   below.
5. **Scoring** - detected answers are compared to your Excel answer
   key using a configurable marking scheme (default: +1 correct,
   -0.25 wrong, 0 blank). A question is "correct" only if the
   student's shaded set exactly matches the key's set - this is what
   makes multi-answer questions (see below) work correctly.
6. **Reporting** - three files, all generated on every run:
   - one Excel file (`output/results.xlsx`) with a `Results` sheet (per
     student, including their looked-up name/class/section), a
     `Question Analysis` sheet (per-question stats across the batch),
     an `Answer Detail` audit trail, and a `Warnings` sheet;
   - one black-and-white, letterhead-branded PDF (`output/student_reports.pdf`)
     with every **validated** student's result, one page after
     another, in roll-number order - the whole batch in a single file
     to print or archive;
   - one diagnostic PDF (`output/bubble_overlay.pdf`) with every
     checked sheet, one page each, showing exactly where the detector
     looked for each bubble and what it decided - see "Bubble overlay
     PDF" below.

## Multi-answer questions

A question's answer key isn't limited to one letter. Multiple letters
in the Answer cell ("B C", "B,C", "BC") are read one of two ways,
controlled by that row's `Is Multi Correct` column:

- `Is Multi Correct` = 0 (or the column isn't in your key file at all):
  the letters are **alternatives** - shading any ONE of them is a
  correct answer on its own ("B C" means "B or C", either alone is
  fine). This is the "any one best response" case, e.g. when more than
  one option in a poorly-worded question turned out to be defensible.
- `Is Multi Correct` = 1: the letters must **all** be shaded together -
  shading only B, or B/C/D, counts as wrong for a "B C" key. This is
  the original multi-select-question behavior, unchanged.

The report always shows however many letters apply - "C" for a single
answer, "B and C" or "B or C" for a multi-answer one - never a generic
"multiple" flag.

## Advanced answer key options

Four optional columns in the answer key spreadsheet (see
`sample_answer_key.xlsx`) override the batch-wide `marking_scheme` on a
per-question basis. Leave any of them blank and that question just
uses the `config.json` default, so a plain Question/Answer-only key
file keeps working exactly as before.

- **Marks** - how many marks a correct (or bonus) answer to this
  question is worth. Blank falls back to `marking_scheme.correct`.
- **Negative Marks** - how many marks are deducted for a wrong answer
  (a positive number - 0.25 means -0.25, not +0.25). Blank falls back
  to `abs(marking_scheme.wrong)`.
- **Is Bonus** - set to 1 to award every student full marks for this
  question automatically, regardless of what they shaded or left
  blank. Shows as "Bonus (Awarded)" everywhere in the reports, and
  always counts as correct - useful for a question later found to be
  flawed or unanswerable, where the fair fix is to give everyone
  credit rather than rescore the batch.
- **Is Multi Correct** - see "Multi-answer questions" above.

For anything more complex than "all of these together" or "any one of
these," write the logic directly into the Answer cell with "and"/"or" -
this always overrides Is Multi Correct, since it's unambiguous either
way:

- `A and B` - both A and B must be shaded together
- `C or D` - either C alone or D alone is accepted
- `A and B or C and D` - exactly {A,B} is accepted, and separately
  exactly {C,D} is also accepted (but not e.g. {A,B,C} or {A} alone)

## Result PDF

`output/student_reports.pdf` has one page per validated student, in
roll-number order: school letterhead and logo (matching the OMR
sheet), a small student photo (downloaded from the school's records if
one's on file - a bordered "No Photo" box otherwise, same size, so the
layout never shifts), the student's name (its own line), father's
name / class-section / ID number, a summary panel (marks, percentage,
attempted, correct/wrong/unattempted, and a bonus count if the key has
any bonus questions), and all 100 questions in a 4-column table showing
your answer, the correct answer, and a Correct/Incorrect/Blank verdict
("Bonus (Awarded)" for a bonus question, regardless of what was
shaded). The source scan filename is noted at
the very bottom of each page, for internal reference only. It's pure
black and white with no background shading - built for printing and
distributing to students (split it into individual pages afterward
with any PDF tool if you need to hand out one at a time), not for
on-screen color coding.

## Bubble overlay PDF

`output/bubble_overlay.pdf` is a diagnostic/audit tool, not part of
scoring - it has one page per checked sheet (the same perspective-corrected
image the detector actually worked from), with a colored circle drawn
at every bubble position the detector looked at:

- **red outline** - checked, found empty
- **solid green** - checked, detected as one of the student's answers
- **solid orange** - the roll-grid digit value read for that position

Use it to visually confirm the detector is looking in the right place
and reaching the right conclusion on a real batch, especially after
changing `fill_threshold` or the sheet template. It's rebuilt from
scratch every `main.py` run alongside the other two reports; pass
`--overlay-pdf` to change its output path.

## Roll number verification

A sheet is only included in `output/student_reports.pdf` once its roll
number is confirmed two ways: read cleanly from the bubbles, AND found
in the school's student records. If either check fails:

1. The sheet's row in `output/results.xlsx` shows `PENDING REVIEW` and
   is highlighted, and it's left out of the result PDF for now.
2. It's added to `output/manual_review.xlsx`, with a cropped close-up
   image of that sheet's roll-number grid so you can read it by eye,
   next to a blank "Actual Roll No" column.
3. Fill in the correct roll number for each row you can identify, save
   the file, then run:
   ```bash
   python tools/resolve_manual_roll.py
   ```
   (defaults to `output/results.xlsx`, `output/manual_review.xlsx`,
   `output/student_reports.pdf` - pass `--results`/`--manual-review`/
   `--reports-pdf` to override)
   This looks up each corrected roll number, updates their row in
   `output/results.xlsx`, and rebuilds `output/student_reports.pdf`
   from scratch so it covers every validated student so far - without
   re-scanning anything, since the detected answers are already saved.
   If a corrected roll number still isn't found, it's reported again
   so you can double check it.

## 1. Install

Requires Python 3.9+, `poppler-utils` (for `pdftoppm`, used to render
the master PDF and rasterize `input/scans.pdf`), and Pango/Cairo (used
by WeasyPrint to render the result PDF):

```bash
# Mac
brew install poppler pango

# Linux
apt install poppler-utils libpango-1.0-0 libpangocairo-1.0-0
```

```bash
cd omr_project
pip install -r requirements.txt
```

## 2. Generate the master layout (one-time, automatic)

```bash
python tools/auto_generate_layout.py --pdf html_answer_sheet/omr_sheet.pdf --output layout.json --dpi 200
```

This is already done and `layout.json` is committed in this project -
you only need to re-run it if you edit
`html_answer_sheet/omr_sheet.html`/`.css` and regenerate the PDF (e.g.
to rebrand it for a different school, or change the question count).

## 3. Try it with the built-in demo (no scanner needed)

Generates realistic synthetic "photographed" sheets covering every
path: a validated roll number (including one multi-answer question
answered correctly and one answered only partially, to show both
sides of multi-answer scoring), a roll number that doesn't exist in
student records, a roll number with one unreadable digit, and a
rotated/backgrounded simulated phone photo - plus combines all of them
into one `scans.pdf`, exactly like a real batch:

```bash
python tools/generate_test_scans.py
```

Then build an answer key from the ground truth and run the checker:

```bash
python -c "
import json, openpyxl
gt = json.load(open('demo/real_sheet_scans/ground_truth.json'))
wb = openpyxl.Workbook(); ws = wb.active; ws.title='AnswerKey'
ws.cell(row=1,column=1,value='Question'); ws.cell(row=1,column=2,value='Answer')
for q in range(1,101):
    ws.cell(row=q+1,column=1,value=q)
    a = gt['key_answers'].get(str(q))
    if a: ws.cell(row=q+1,column=2,value=a)
wb.save('demo/real_sheet_scans/test_answer_key.xlsx')
"
python main.py --scans-pdf demo/real_sheet_scans/scans.pdf --answer-key demo/real_sheet_scans/test_answer_key.xlsx --output demo/real_sheet_scans/results.xlsx --reports-pdf demo/real_sheet_scans/student_reports.pdf --manual-review demo/real_sheet_scans/manual_review.xlsx --overlay-pdf demo/real_sheet_scans/bubble_overlay.pdf
```

Open `demo/real_sheet_scans/results.xlsx` for the batch report -
you'll see most rows resolved with the student's name/class/section
filled in, and a couple marked `PENDING REVIEW`; open
`demo/real_sheet_scans/manual_review.xlsx` to see those with their
cropped roll-grid images, and `demo/real_sheet_scans/student_reports.pdf`
for the finished results, one page per validated student.

## 4. Set up for your real sheets

### a) Print the sheet

Print `html_answer_sheet/omr_sheet.pdf` as-is - don't crop or rescale
it, since that would move the registration markers relative to where
`layout.json` expects them.

### b) Scan or photograph filled sheets

- Use good, even lighting; avoid shadows across the bubble grid.
- Capture the full sheet including all four corners (needed to detect
  the registration markers).
- Roll number is read automatically from the bubbled Roll Number grid
  on the sheet - it does not need to be written on the filename or
  tracked anywhere separately.
- Combine the whole batch into **one PDF**, one page per sheet, saved
  as `input/scans.pdf` - most scanners do this automatically with a
  "scan to PDF" or ADF (auto document feeder) mode; if you're using
  loose photos instead, combine them into one PDF with any tool you
  like (e.g. your phone's "Print to PDF"/scanning app, or a PDF
  editor). Page order doesn't matter - each page is scored
  independently.
- (Fallback: if `input/scans.pdf` doesn't exist, the tool will instead
  look for separate image files in `input/scans/` - useful if you'd
  rather manage individual scan files.)

### c) Prepare the answer key

Generate a blank template and fill in the correct answers:

```bash
python tools/generate_sample_key.py --output input/answer_key.xlsx
```

Open `input/answer_key.xlsx` and fill the `Answer` column for each
question - one letter for a normal question ("C"). Leave a question
blank if the exam doesn't actually have that many questions - it's
excluded entirely rather than counted against students.

The template also has four optional columns for anything beyond a
plain single-letter answer - see "Advanced answer key options" below.
Leave them all blank/0 and every question just uses the batch-wide
`marking_scheme` from `config.json`, exactly like a plain Question/
Answer-only key file always has.

### d) Run the checker

```bash
python main.py
```

All input is read from `input/` and every generated file is written to
`output/` by default - no flags needed for the standard layout. Pass
`--scans-pdf`/`--scans-dir`/`--answer-key`/`--output`/`--reports-pdf`/
`--manual-review`/`--overlay-pdf` only if you want different paths.

Open `output/results.xlsx`:
- **Results** - roll no, looked-up name/class/section, attempted/
  correct/wrong/unattempted counts, marks, percentage. Rows still
  awaiting manual roll verification show `PENDING REVIEW` and are
  highlighted.
- **Question Analysis** - per-question marks/negative marks/bonus/
  multi-correct settings actually used, option distribution, and
  facility index (% who got it right) - useful for spotting a
  mis-keyed or unusually hard question.
- **Answer Detail** - every detected answer per student (e.g. "C" or
  "B C"), for spot-checking against the physical sheet.
- **Warnings** - anything that needs your attention.

`output/student_reports.pdf` has the ready-to-print result for every
validated student, one page each, in roll-number order (see "Result
PDF" above). `output/bubble_overlay.pdf` shows exactly where each
bubble was checked and what was detected (see "Bubble overlay PDF"
above). `output/manual_review.xlsx` lists anything still pending (see
"Roll number verification" above).

## Configuration

Edit `config.json` to change:
- `fill_threshold` - how dark a bubble must be (0-1) to count as
  filled. Raise if faint pencil marks are being missed; lower if
  clean marks are being missed.
- `ambiguous_margin` - how close two roll-number digit values can be in
  darkness before that digit is treated as unclear (this no longer
  affects question bubbles, which support multiple selections).
- `marking_scheme` - marks for correct/wrong/unattempted.
- `render_dpi` - must match the DPI used when generating `layout.json`.
- `scan_pdf_dpi` - resolution used to rasterize `input/scans.pdf` pages
  before detection. Independent of `render_dpi`/`layout.json` -
  marker-based perspective correction works at any resolution.
- `student_info_api_base` - the school records lookup endpoint.
- `pending_review_dir` - where cropped roll-grid images are saved for
  sheets awaiting manual review (default `output/pending_review`).

## Project layout

```
omr_project/
├── main.py                        # CLI entry point
├── config.json                    # marking scheme, detection thresholds, sheet geometry
├── requirements.txt
├── layout.json                    # auto-generated bubble + marker coordinates
├── html_answer_sheet/
│   ├── omr_sheet.html/.css        # sheet source (edit + re-export to change the template)
│   └── omr_sheet.pdf              # the master, print-ready sheet
├── omr/
│   ├── preprocessing.py           # marker detection + perspective correction
│   ├── pdf_input.py               # rasterizes input/scans.pdf into one image per page
│   ├── bubble_detector.py         # fill detection (multi-select questions + roll number)
│   ├── answer_key.py              # reads the Excel answer key (supports multi-answer questions)
│   ├── scoring.py                 # marks + question stats (set-based multi-answer matching)
│   ├── student_info.py            # school records API lookup by roll number
│   ├── manual_review.py           # roll-grid image cropping + manual_review.xlsx
│   ├── report.py                  # writes the batch Excel report
│   ├── student_report.py          # renders each student's page in memory and merges them into one PDF
│   └── overlay.py                 # diagnostic PDF: draws where every bubble was checked + what was found
├── tools/
│   ├── auto_generate_layout.py    # ONE-TIME automatic calibration from the master PDF
│   ├── generate_sample_key.py     # blank answer-key template generator
│   ├── generate_test_scans.py     # synthetic demo/test data generator (+ combined scans.pdf)
│   └── resolve_manual_roll.py     # finishes sheets after a human fills in the correct roll number
├── input/                         # everything main.py reads
│   ├── scans.pdf                  # ALL scanned sheets for the batch, one page each (primary input)
│   ├── scans/                     # fallback: separate scan image files, used only if scans.pdf is absent
│   └── answer_key.xlsx            # the correct answers for this batch
├── output/                        # everything main.py/resolve_manual_roll.py generate
│   ├── results.xlsx               # batch Excel report
│   ├── student_reports.pdf        # every validated student's result, one PDF, roll-number order
│   ├── bubble_overlay.pdf         # diagnostic: red/green/orange bubble-check overlay, one page per sheet
│   ├── manual_review.xlsx         # sheets needing manual roll verification
│   ├── pending_review/            # cropped roll-grid images awaiting manual review
│   └── student_photos/            # downloaded student photos, cached by ID
└── demo/                          # synthetic demo data (safe to delete)
```

## Limitations / notes

- Photos are assumed roughly right-side-up (not upside-down or rotated
  90 degrees) - the 4 registration squares are visually identical, so
  orientation can't be recovered from them alone. Moderate rotation/skew
  (tested up to a few degrees plus perspective distortion) is fine.
- All 4 corners must be visible in the photo for marker-based
  correction to work; if a corner is cropped out of frame, the tool
  falls back to a less precise whole-sheet-outline detection.
- Sheets with heavy folds or shadows across the bubble area may need
  re-scanning; anything the tool can't confidently read is flagged in
  the `Warnings` sheet and highlighted rows in `Results`, not silently
  guessed.
- The student records lookup (`dlcs.managemyschools.in`) requires
  normal internet access from wherever you run `main.py`; it needs no
  authentication from what's been confirmed, but if that ever changes
  you'd add credentials to the request in `omr/student_info.py`.
- A student only gets a printed result once their roll number is
  confirmed - see "Roll number verification" above for the review/
  resolve workflow for anything that isn't.
- Re-run `tools/auto_generate_layout.py` only if you change the sheet
  template itself (different question count, layout, or paper size).
- Rasterizing `input/scans.pdf` requires `pdftoppm` (poppler-utils,
  already needed to render the master sheet - see "Install" above).
- No per-student PDF files are ever written to disk - every page is
  rendered in memory and merged straight into `output/student_reports.pdf`.
  If you need to hand a single page to one student, split it out of
  that PDF with any PDF tool (e.g. `pdf` skill, `qpdf`, Preview/Acrobat).
