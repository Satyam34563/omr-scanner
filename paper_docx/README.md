# Question Paper Generation Pipeline

Turns `questions.db` (built by the Book Question Extraction workflow) into a
CBSE/JNV-style exam paper — plus a matching answer key and an explained
answer key — as three `.docx` files, from a config you (or Claude) write in
one message.

## What it produces

From one config file, three Word documents:

1. **`<name>_question_paper.docx`** — the exam itself. A4, narrow (0.5")
   margins, black text on white only (a single vertical rule between the two
   question columns is the only line in the layout). A 2-column school
   header (logo + school info) up top, then General Instructions, then each
   section; Session and Date sit in the footer, not the header. Directions/
   passages are always full width; questions flow in a genuine two-column
   Word layout — not a paired table — so a short question doesn't force its
   neighboring column to start at the same line, and each question is
   wrapped so it can never split mid-way across a column or page break.
   Every fraction/exponent/subscript/root is a real, editable Word equation
   (OMML) — not a Unicode approximation. Options are always relabeled
   a/b/c/d and auto-pick the most compact layout that fits: one row of
   four, a 2×2 grid, or a vertical list (image-option labels sit centered
   directly below the image).
2. **`<name>_answer_key.docx`** — just `Q# → (answer)`, packed into a
   compact multi-column grid so it fits a page or two, ready to hand out
   separately at the end of the exam.
3. **`<name>_answer_key_explained.docx`** — the same answers, each followed
   by its explanation (also math-aware), one per question, full width.

## How to run it

```bash
./generate.sh <config.json> <outdir>
```

This runs both stages:

```bash
python3 select_questions.py --db questions.db --config config.json \
  --image-base <QUESTION_BANK folder> --out paper_content.json
node build_docx.js paper_content.json --outdir <outdir> --school-config school_config.json
```

`QUESTION_BANK_DIR` env var (or the default baked into `generate.sh`) must
point at the folder containing `questions.db` and `images/`.

**Dependencies** (already installed in this pipeline folder): Node's `docx`
(v9.7+, for OMML math support) and `image-size` packages (`npm install` in
this directory), Python 3 stdlib only (uses `sqlite3`, no extra pip
packages).

## Writing a config

```jsonc
{
  "paper_title": "Model Test Paper 1",
  "output_name": "model_test_1",          // used as file prefix
  "exam_duration": "2 Hours",             // ASK THE USER for this before generating; defaults to "2 Hours" if omitted
  "numbering": "continuous",              // or "per_section" (Q1 restarts each section)
  "selection_mode": "random",             // default; or "sequential" (first-N instead of random sample)
  "random_seed": 42,                      // only used when selection_mode = "random"
  "shortfall_strategy": "redistribute",   // or "allow_shortfall" — see below
  "sections": [
    {
      "section_name": "MENTAL ABILITY TEST",   // must match `sections.name` in the DB
      "total_questions": 40,
      "chapters": null                          // null/{} = equal split across all chapters that have questions
    },
    {
      "section_name": "ARITHMETIC TEST",
      "total_questions": 20,
      "chapters": {                             // OR give explicit per-chapter counts
        "Number and Numeric System": 5,
        "Percentage and its Applications": 3
      }
    },
    {
      "section_name": "LANGUAGE TEST (ENGLISH)",
      "mode": "passages",                       // comprehension is grouped by passage, not chapter
      "num_passages": 4,
      "questions_per_passage": null             // null = every question tied to the chosen passage; or a number to cap it
    }
  ]
}
```

Maximum Marks is **not** a config field — it's always computed automatically
as `total_questions × 1.5` at render time (Part 2 of the formatting spec).

### Section selection modes

- **Equal split** (`chapters: null` or `{}`): the section's `total_questions`
  is divided evenly across every chapter in that section that has at least
  one question available (`base = total_questions // n_chapters`). Any
  leftover chapters (0 questions in the DB) are skipped and logged as a
  warning. If the total doesn't divide evenly, or a chapter runs short and
  `shortfall_strategy` is `redistribute`, WHICH chapters absorb the extra
  question(s) is randomized each run — not always the same first chapters
  by `chapter_number`.
- **Explicit counts** (`chapters: {"Chapter Name": N, ...}`): pulls exactly
  N from each named chapter. If the DB has fewer than N, you get however
  many exist, and a warning is logged — no silent guessing.
- **Passages mode** (`"mode": "passages"`): for comprehension-style sections.
  Picks `num_passages` distinct passages (reading_comprehension context
  blocks) and includes either all their questions or a capped number per
  passage (`questions_per_passage`).

### Shortfall handling (equal-split sections only)

If a section's chapters can't collectively supply `total_questions` (e.g. a
chapter has 0 or 1 questions in the DB):

- `"redistribute"` (default) — give the missing questions to chapters that
  have spare capacity, so the section total still hits target where possible.
- `"allow_shortfall"` — take whatever exists and let the section land under
  target; a warning records the shortfall.

Either way, every gap is written to the console output and into
`paper_content.json`'s `"warnings"` array — nothing is silently dropped.

## School header / branding (`school_config.json`)

```jsonc
{
  "school": "Divine Light Central School",  // always rendered in CAPITALS, bold, prominent
  "logo": "logo.png",                       // path relative to this JSON file, or absolute
  "displayFont": "Georgia",                 // applied as the document's default font throughout
  "session": "2026-27",                     // optional, shown in the FOOTER (e.g. "Session: 2026-27  |  Date: ___")
  "addressLines": [                         // optional, each printed on its own line, exactly as given
    "SHIVPURI, RAMCHANDRAPUR, BIHARSHARIF (NALANDA)",
    "Recognized by Government of Bihar under R.T.E. 2009",
    "Reg. Code : 22913862022930162008",
    "Web: divinelightcentralschool.com, Ph No: 8340220267"
  ],
  "defaultInstructions": [
    "Read all the questions carefully before answering. ...",
    "..."
  ]
}
```

`logo.png` currently ships as a generic placeholder monogram (also saved as
`logo_placeholder.png`) purely so the 2-column header can be demonstrated —
replace it with the school's real crest file before handing out an actual
paper.

- If `logo` doesn't point at a real file, the header **gracefully degrades**
  to a single centered column (school name + info only) — point `logo` at a
  real crest to activate the true 2-column header (logo left, vertically
  centered, aspect ratio preserved, never stretched; school info column with
  the name prominent and the rest beneath it). A generic placeholder
  (`logo_placeholder.png`, a plain circular monogram) ships in this folder
  purely so the 2-column layout can be demonstrated/verified — swap it for
  the school's real logo file before handing out an actual paper.
- `defaultInstructions` are rendered as a numbered "General Instructions"
  block right after the header/exam-info line.
- Pass a different school file per run with `--school-config path.json` if
  you generate papers for more than one school/brand.

## Math rendering (real OMML, never Unicode-faked)

`mathToOmml.js` scans every question stem, option, and explanation string
for structural math and emits genuine Word equation objects via the `docx`
package's Math API (`Math`, `MathFraction`, `MathSuperScript`,
`MathSubScript`, `MathRadical`, `MathSum`, `MathIntegral`) — the same OMML
Word's own Equation Editor produces, fully editable in Word.

Detected today: simple fractions (`5/8`), mixed numbers (`15½`, `1 3/4`),
unicode vulgar fractions (`¾`), square roots (`√9`, `sqrt(x+1)`), caret and
unicode superscript exponents (`x^2`, `x²`), subscripts (`a_1`), and bare
summation/integral signs with `_lower^upper` limits. Plain arithmetic
(`×  ÷  −  +  =  %` between plain numbers) is deliberately left as normal
text — that's standard exam-paper typesetting, not something OMML needs to
own. Matrices aren't auto-detected (the current book has none); `buildMatrix()`
is stubbed in `mathToOmml.js` for a future book that needs one — flag those
questions for manual review rather than guessing a layout.

**Known limitation:** the detector is regex/heuristic-based, not a full
expression parser. Unusual notation (nested exponents-of-exponents, custom
symbols) may not be recognized and will render as plain text instead of
OMML. Spot-check math-heavy sections after generating (see verification
step below) and hand-fix any missed equation directly in Word if needed.

## Two-column question layout

Questions flow in a **real Word section with `column: {count: 2, separate:
true}`** — not a paired table. `build_docx.js` walks the paper and splits it
into alternating "full width" runs (headers, section titles, directions,
passages) and "two column" runs (the questions themselves), emitting one
actual `docx` section per run (`SectionType.CONTINUOUS`, so there's no
forced page break between them). Because it's genuine column flow, a short
question doesn't force its neighboring column to start at the same
line — Word fills the left column, then continues at the top of the right
column, then wraps to the next page, same as a newspaper or textbook. The
single vertical rule between columns is Word's own column separator
(`separate: true`), not a manual border.

**Every question is atomic.** `renderQuestionInline()` wraps a question's
whole content — stem, figure, options — inside a single borderless
one-cell table with `cantSplit: true`. Testing showed `keepNext` chains
across mixed paragraph/table content are not reliably honored across a
column break by every renderer (LibreOffice would still separate a stem
from its own image/options); a `cantSplit` table row is a much stronger
guarantee — the whole question moves to the next column/page as one unit
rather than breaking mid-way.

**Grouping key is the chapter, not the exact direction text — and each
chapter gets exactly ONE direction, period.** The first "direction"-type
block encountered in a chapter is printed once; every later question in
that same chapter is treated as already covered, even if its own
`context_block_id` points at a differently-worded variant (e.g. a
lettered-options vs numbered-options phrasing of the same "odd one out"
task) — it is never restated. This rule is direction-specific:
"passage"-type blocks are exempt and still print once per distinct
passage, right before their own questions, since each reading passage is
genuinely unique content the following questions depend on. Section
headings are underlined only; directions and passages carry no border box,
just the bold-italic "Directions:"/"Passage:" label.

Options are always relabeled `a, b, c, d...` regardless of how the source
book labeled them (see `LETTERS` remap in `select_questions.py` — the
answer key is remapped by position too, so it stays consistent with what's
printed). Image options: the label sits centered directly below the image,
never above it.

PYQ tags show only `(year)` — never the exam name — and only when
`is_pyq` is true for that question.

## Exam info, footer & instructions

The Time Allowed / Maximum Marks / Total Questions line is a borderless
3-column table spread edge-to-edge across the full page width. Session and
Date live in the **footer** instead (`Session: 2026-27  |  Date:
___________`) — `exam_date` is an optional `select_questions.py` config
field; if omitted it prints as a blank line for manual fill-in.

General Instructions are generated dynamically from the actual paper
structure: (1) number of sections with their question counts, (2) marks per
question and section-wise marks breakdown, (3) the first static instruction
listed in `school_config.json`'s `defaultInstructions` (only the first —
the rest are dropped to keep the list short and readable). Every question
is marked at a uniform `MARKS_PER_QUESTION` (1.5, matching the Maximum
Marks formula) — the DB's per-question `marks` field is not used for
display, to keep the paper internally consistent.

Question and option figures are capped at a smaller max size than earlier
drafts (question figures ≤1.7"×1.3", option images ≤0.85"×0.65") purely to
cut wasted blank space — `safeImageDims()` never upscales, so small source
images are still shown at their native size either way.

Within each question, options auto-select layout by estimating rendered
width: a single row of four if everything (including any option images)
fits; otherwise a balanced 2×2 grid; otherwise a vertical list. The label
always stays on the same line as its content.

## Files in this folder

| File | Purpose |
|---|---|
| `select_questions.py` | Stage 1 — reads config + DB, resolves selection, writes `paper_content.json` |
| `build_docx.js` | Stage 2 — reads `paper_content.json` + `school_config.json`, writes the 3 `.docx` files |
| `mathToOmml.js` | Text → OMML converter used by `build_docx.js` for every question/option/explanation string |
| `generate.sh` | Runs both stages in order |
| `config_standard_preset.json` | Example config matching the "Standard" preset |
| `school_config.json` | Example school branding config (no real logo yet — see above) |
| `node_modules/` | `docx` + `image-size` npm packages |

## Verifying a run before handing it to the user

```bash
python scripts/office/soffice.py --headless --convert-to pdf <name>_question_paper.docx
pdftoppm -jpeg -r 100 <name>_question_paper.pdf page
```

Then read a few page images back to confirm: header renders (2-col if a
logo is present), Maximum Marks = total×1.5, no shading/color anywhere,
questions pair correctly, math renders as true equations (not raw text with
`/` or `^` visible), and PYQ tags only appear on actual PYQ questions.

## Extending it later

- To support a new question type's rendering (e.g. match-the-following
  combination codes), the generic option renderer already handles arbitrary
  label/text/image pairs — no changes needed unless you want type-specific
  formatting.
- To reuse this against a different book's `questions.db`, just point
  `QUESTION_BANK_DIR` at the new folder and match `section_name` /
  `chapters` values in your config to that book's actual section and
  chapter names.
- To add a math pattern the detector misses, add a `{name, re}` entry to
  `PATTERNS` in `mathToOmml.js` and a matching `case` in `textToRuns()`.
