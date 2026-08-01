# Question Paper Generator — Project Instructions

## Task

Generate CBSE/JNV-style examination papers from `questions.db` (built by the
Book Question Extraction project) using the pipeline in `paper_pipeline/`.
For every request: ask which sections/chapters/counts to include (or accept
the "Standard preset"), ask the exam duration (default "2 Hours" if not
given) and the exam date (blank fill-in line if not given), then run the
pipeline and hand back three `.docx` files.

## Where things live

- `questions.db`, `images/` — the question bank (read-only source of truth).
- `paper_pipeline/select_questions.py` — Stage 1: resolves a JSON config into
  a selected question set (`paper_content.json`); also relabels every
  question's options to a/b/c/d and remaps `correct_answer` to match.
- `paper_pipeline/build_docx.js` — Stage 2: renders the 3 Word documents.
- `paper_pipeline/mathToOmml.js` — text → real OMML equation converter.
- `paper_pipeline/school_config.json` — header/footer/branding config.
- `paper_pipeline/generate.sh <config.json> <outdir>` — runs both stages.
- `paper_pipeline/README.md` — full schema reference; read it before writing
  a new config or touching the renderer.

## Workflow for every request

1. Read `paper_pipeline/README.md` if it's been a while since the config
   schema was last used — it's the source of truth, more so than this file's
   summary below.
2. Ask (or confirm) which sections, chapters, and per-chapter counts to
   include — empty/omitted chapters means an equal split. Offer the
   "Standard preset" (`config_standard_preset.json`) as a shortcut when the
   user doesn't specify otherwise.
3. Ask the exam duration and exam date. Default duration to "2 Hours" and
   date to a blank fill-in line if the user doesn't answer — never fabricate
   either.
4. Write a config JSON reflecting the answers, run
   `./generate.sh <config.json> <outdir>`, and check the console output for
   warnings (shortfalls, missing chapters/sections) — surface these to the
   user rather than silently absorbing them.
5. Convert the question paper to PDF and spot-check a few pages (header,
   a math-heavy question, an option layout, a chapter transition with
   directions) before handing the files back.

## Formatting standards (must hold for every generated paper)

**Header.** A 2-column table: logo (left-aligned, vertically centered,
aspect-ratio preserved, never stretched) beside the school name — always
rendered in CAPITALS — with address lines beneath it. Driven by
`school_config.json`. If no real logo file is present, the header degrades
to a single centered column rather than showing a broken image — that's
expected, not a bug; get a real logo file from the user to activate the
2-column layout. Session and Date are NOT in the header — they're in the
**footer** (`Session: ...  |  Date: ...`), which appears on every page.

**Exam info.** Time Allowed / Maximum Marks / Total Questions sit in a
borderless 3-column row spread edge-to-edge across the page. Maximum Marks
is always `total_questions × 1.5`, computed automatically — never asked
for, never manually overridden. Every question tag also shows 1.5 marks
uniformly (not the source book's own per-question marks value), so the
paper is internally consistent throughout.

**General Instructions.** Generated dynamically, not hand-written: (1) a
sentence naming every section and its question count, (2) marks per
question plus section-wise marks breakdown, (3) the *first* entry only from
`school_config.json`'s `defaultInstructions` (deliberately short — don't
add more procedural boilerplate back in unless asked).

**Math.** Every fraction, exponent, subscript, square root, summation, and
integral must be a real OMML equation object (Word's own Equation Editor
format), never a Unicode slash/caret approximation. `mathToOmml.js` handles
this automatically for question stems, options, and explanations. Plain
arithmetic operators (× ÷ − + = %) between plain numbers stay as normal
text — only genuinely structural math needs an equation object. Verify a
math-heavy page after every generation run — the detector is regex-based,
not a full parser, and unusual notation can slip through as plain text.

**Visual design.** Black text on white only, throughout the question
paper, answer key, and explained answer key alike. No shading, no
highlighting, no background color on directions or passages. The **only**
line in the whole question-paper layout is the vertical rule between the
two question columns — section headings are underlined text, not
boxed/ruled; directions and passages get no border at all.

**Options.** Always relabeled a/b/c/d — regardless of how the source book
labeled them — with the answer key remapped by position to match. Layout
auto-selects the most compact fit: a single row of four, else a balanced
2×2 grid, else a vertical list. Image-option labels sit centered directly
*below* the image, never above it. Images never upscale past their native
size; question figures and option images are capped small specifically to
avoid wasting page space.

**PYQ tags.** Show only `(year)` — never the exam name — and only when
`is_pyq` is true for that question.

**Chapter-scoped directions.** All questions in the same chapter share ONE
direction, shown once, even if some of those questions individually
reference a differently-worded variant (e.g. lettered vs numbered option
phrasing of the same task) — later variants in the same chapter are never
restated. This does NOT apply to reading passages: each distinct passage
still prints once, right before its own questions, since the following
questions genuinely depend on that specific text.

**Layout mechanics.** Questions flow in a real two-column Word section
(`column: {count: 2, separate: true}`), not a paired table — a short
question doesn't force its neighboring column to start at the same line.
Every question is wrapped in an atomic `cantSplit` table so it can never
break mid-way across a column or page boundary. Directions/passages/
section headings/instructions always render in a full-width single-column
section between the two-column question runs.

## Known limitations to disclose, not silently paper over

- The math converter is heuristic (regex-based). Flag anything that looks
  like it should have been an equation but rendered as plain text.
- Matrix questions are not auto-converted to OMML matrices (the `docx`
  package has no native matrix primitive as of v9.7); flag any matrix
  question for manual review rather than guessing a layout.
- A missing logo file degrades the header gracefully rather than erroring
  — tell the user if they want the true 2-column branded header, they need
  to supply a real logo file (there's a placeholder monogram shipped for
  demo purposes only).
