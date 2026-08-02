#!/usr/bin/env node
/**
 * build_docx.js — Stage 2 of the question-paper pipeline.
 *
 * Consumes paper_content.json (produced by select_questions.py) plus
 * school_config.json (header/branding) and writes three .docx files:
 *   <prefix>_question_paper.docx       — the exam paper itself
 *   <prefix>_answer_key.docx           — compact answer key only
 *   <prefix>_answer_key_explained.docx — answer key + explanations
 *
 * CBSE/JNV-style formatting standards implemented here:
 *   - A4, narrow (0.5in) margins, black text on white only (no shading,
 *     only a single vertical rule between the two question columns)
 *   - 2-column school header table (logo | school info), Georgia default
 *     font; Session + Date live in the footer, not the header
 *   - Maximum Marks auto-computed as total_questions * 1.5
 *   - Real OMML equations (fractions/exponents/subscripts/roots) via
 *     mathToOmml.js — never Unicode-faked math
 *   - Directions/passages/instructions: always full width, never inside
 *     the 2-column question layout; one direction per chapter, period
 *   - Questions flow in a genuine 2-column Word section (not a paired
 *     table), so a short question doesn't force its neighboring column to
 *     start at the same line; each question is wrapped in an atomic
 *     cantSplit table so it can never break mid-way across a column/page
 *   - Options always relabeled a/b/c/d; per-question layout auto-chosen:
 *     1x4 -> 2x2 -> 4x1; image-option labels sit centered below the image
 *   - PYQ year/exam tag only rendered when is_pyq is true
 *
 * Usage:
 *   node build_docx.js paper_content.json --outdir ./out --prefix name \
 *     --school-config school_config.json
 */
const fs = require("fs");
const path = require("path");
const sizeOf = require("image-size").default || require("image-size");
const { Jimp, JimpMime } = require("jimp");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  WidthType, BorderStyle, AlignmentType, VerticalAlign, SectionType, Footer, Header,
  PageNumber, LevelFormat, LevelSuffix, ShadingType, LineRuleType, Tab, TabStopType,
  HorizontalPositionAlign, HorizontalPositionRelativeFrom,
  VerticalPositionAlign, VerticalPositionRelativeFrom, TextWrappingType,
} = require("docx");
const { textToRuns } = require("./mathToOmml.js");

// ---------- typography (standing spec: Cambria throughout, exact point sizes) ----------
// docx TextRun `size` is in half-points (so 16pt -> 32, 10.5pt -> 21, etc).
const FONT_SIZE = {
  mainHeading: 32,     // Cambria Bold 16pt
  sectionHeading: 26,  // Cambria Bold 13pt
  question: 22,        // Cambria 11pt
  option: 21,           // Cambria 10.5pt
  directions: 20,      // Cambria Italic 10pt
  generalInstructions: 20, // Cambria 10pt
  small: 16,           // misc small print (marks tag, PYQ tag, missing-image notices)
};

// ---------- image preprocessing: trim transparent/uniform margins before scaling ----------
// Populated once per run by preprocessImages() (called from main(), async) so
// the rest of the (synchronous) rendering code can look images up instantly.
// Falls back to reading the raw file directly if a path wasn't preprocessed
// (e.g. autocrop failed) — never a hard error.
let _imageCache = new Map(); // filePath -> { buf: <trimmed PNG buffer>, width, height }

async function preprocessImages(data, school) {
  const paths = new Set();
  for (const sec of data.sections) {
    for (const q of sec.questions) {
      (q.question_images || []).forEach((p) => paths.add(p));
      (q.options || []).forEach((o) => { if (o.image) paths.add(o.image); collectInlineImagePaths(o.text, paths); });
      collectInlineImagePaths(q.question_text, paths);
      collectInlineImagePaths(q.explanation, paths);
    }
  }
  // inline images referenced from context blocks (passages / directions)
  if (data.context_blocks) {
    Object.values(data.context_blocks).forEach((b) => collectInlineImagePaths(b && b.text, paths));
  }
  if (school.logo && fs.existsSync(school.logo)) paths.add(school.logo);

  await Promise.all([...paths].map(async (p) => {
    try {
      const img = await Jimp.read(p);
      img.autocrop(); // trims uniform-color/transparent margins before any scaling decision
      const buf = await img.getBuffer(JimpMime.png);
      _imageCache.set(p, { buf, width: img.width, height: img.height });
    } catch (e) {
      // leave uncached — safeImageDims() transparently falls back to the raw file
    }
  }));
}

// ---------- school-logo watermark (standing rule, every generated paper) ----------
// A faint, greyscale, low-opacity copy of the school logo, floated behind the
// text and centered on the page via a real repeating Word header — appears
// on every page of every one of the 3 docs. Prepared once (async, alongside
// preprocessImages) into _watermarkBuf/_watermarkDims; buildWatermarkHeader()
// then just synchronously wraps that buffer in a fresh Header per section.
let _watermarkBuf = null;
let _watermarkDims = null;

async function prepareWatermark(school) {
  _watermarkBuf = null;
  _watermarkDims = null;
  if (!school.logo || !fs.existsSync(school.logo)) return;
  try {
    const img = await Jimp.read(school.logo);
    img.autocrop();
    img.greyscale();
    img.opacity(0.10); // faint — must never compete with the actual page content
    const buf = await img.getBuffer(JimpMime.png);
    _watermarkBuf = buf;
    _watermarkDims = { width: img.width, height: img.height };
  } catch (e) {
    // no watermark rather than a hard failure — a missing/unreadable logo
    // shouldn't block generating the paper.
  }
}

const WATERMARK_SIZE_MM = 120; // large, centered, behind text

function buildWatermarkHeader(font) {
  if (!_watermarkBuf || !_watermarkDims) return new Header({ children: [new Paragraph({ children: [] })] });
  const capPx = mm(WATERMARK_SIZE_MM);
  const scale = Math.min(capPx / _watermarkDims.width, capPx / _watermarkDims.height);
  const width = Math.round(_watermarkDims.width * scale);
  const height = Math.round(_watermarkDims.height * scale);
  return new Header({
    children: [new Paragraph({
      children: [new ImageRun({
        data: _watermarkBuf,
        transformation: { width, height },
        type: "png",
        floating: {
          horizontalPosition: { relative: HorizontalPositionRelativeFrom.PAGE, align: HorizontalPositionAlign.CENTER },
          verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, align: VerticalPositionAlign.CENTER },
          behindDocument: true,
          allowOverlap: true,
          wrap: { type: TextWrappingType.NONE },
        },
      })],
    })],
  });
}

// ---------- real Word list numbering (numPr) for question numbers & option letters ----------
// Every question paragraph and every option-label paragraph gets its own
// single-entry numbering list (started at the exact value already resolved
// by select_questions.py), rather than a typed "Q1. "/"(a) " text run. This
// keeps the printed number/letter a genuine, editable Word list marker (per
// the "Question numbering"/"Options" formatting spec) while trivially
// matching whatever numbering mode (continuous/per_section) Stage 1 already
// resolved into `display_number` and each option's array position.
let _numberingConfig = null; // set per-document by the caller, mutated as blocks are built
let _showQuestionMarks = true; // whether each question shows its "[N Marks]" tag (per-paper option)
let _forceMA1x4 = false; // force Mental Ability options into a single 1x4 row (per-paper option)
let _paperLanguage = null; // paper language (drives the English Mental Ability figure rule)
let _numRefCounter = 0;

function nextNumRef(prefix) {
  _numRefCounter += 1;
  return `${prefix}-${_numRefCounter}`;
}

function registerQuestionNumbering(startAt) {
  const ref = nextNumRef("qnum");
  _numberingConfig.push({
    reference: ref,
    levels: [{
      level: 0,
      format: LevelFormat.DECIMAL,
      text: "%1.",
      start: startAt,
      suffix: LevelSuffix.SPACE,
      alignment: AlignmentType.START,
      style: { run: { bold: true, size: 20 }, paragraph: { indent: { left: 0, hanging: 0 } } },
    }],
  });
  return ref;
}

function registerOptionNumbering() {
  // One shared reference per question so its options increment a, b, c, d
  // in document order; a fresh reference per question restarts at "a)".
  const ref = nextNumRef("optlet");
  _numberingConfig.push({
    reference: ref,
    levels: [{
      level: 0,
      format: LevelFormat.LOWER_LETTER,
      text: "%1)",
      suffix: LevelSuffix.SPACE,
      alignment: AlignmentType.START,
      style: { run: { bold: true, size: 20 }, paragraph: { indent: { left: 0, hanging: 0 } } },
    }],
  });
  return ref;
}

// ---------- Hindi-book section display names (standing user preference) ----------
// The DB's raw section_name ("MENTAL ABILITY TEST (HINDI BOOK)", etc.) is
// still the identifier used for config matching/lookups everywhere else in
// the pipeline; this map only swaps what's *printed* as the section heading
// (and drives the Hindi "Directions" label) for these specific sections —
// English-sourced sections are untouched.
const HINDI_SECTION_DISPLAY_NAMES = {
  "MENTAL ABILITY TEST (HINDI BOOK)": "मानसिक योग्यता परीक्षण",
  "ARITHMETIC TEST (HINDI BOOK)": "अंकगणितीय परीक्षण",
  "ARITHMETIC TEST - EXTRA CHAPTERS (HINDI BOOK)": "अंकगणितीय परीक्षण (अतिरिक्त अध्याय)",
  "LANGUAGE TEST (HINDI BOOK)": "भाषा परीक्षण",
  "ENVIRONMENTAL STUDIES (HINDI BOOK)": "पर्यावरण अध्ययन",
};

function displaySectionName(rawName) {
  return HINDI_SECTION_DISPLAY_NAMES[rawName] || rawName;
}

function isHindiSection(rawName) {
  return Object.prototype.hasOwnProperty.call(HINDI_SECTION_DISPLAY_NAMES, rawName);
}

// ---------- geometry (A4, narrow 0.5in margins) ----------
const PAGE_WIDTH = 11906;
const PAGE_HEIGHT = 16838;
const MARGIN = 720; // 0.5in narrow margin
const CONTENT_WIDTH = PAGE_WIDTH - MARGIN * 2; // 10466
const COL_GUTTER = 240; // gutter between the two question columns (twips)
const COL_WIDTH = (CONTENT_WIDTH - COL_GUTTER) / 2;

const MARKS_PER_QUESTION = 1.5; // Maximum Marks = total_questions * 1.5 (Part 2); applied uniformly per question too, for internal consistency

const PAGE_SETUP = {
  size: { width: PAGE_WIDTH, height: PAGE_HEIGHT },
  margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
};

const BLACK = "000000";
const NO_BORDERS = {
  top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
  left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
  insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE },
};

function px(inches) { return Math.round(inches * 96); }
function pxToTwips(pxVal) { return Math.round(pxVal * 15); } // 1440 twips/in / 96 px/in
const MM_PER_INCH = 25.4;
function mm(v) { return px(v / MM_PER_INCH); } // mm -> px @96dpi, for the size-tier caps below

function safeImageDims(filePath, maxWidthPx, maxHeightPx) {
  try {
    const cached = _imageCache.get(filePath);
    const buf = cached ? cached.buf : fs.readFileSync(filePath);
    const dims = cached ? { width: cached.width, height: cached.height } : sizeOf(buf);
    let w = dims.width, h = dims.height;
    const scale = Math.min(maxWidthPx / w, maxHeightPx / h, 1); // never upscale past native size
    return { buf, width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)) };
  } catch (e) {
    return null;
  }
}

// ---- Consistent per-role image sizing (Part: "same size across the paper") ----
// Instead of "fit in a box, never upscale" (which let each image's SOURCE pixel
// count decide its size -> wildly inconsistent), we scale every image to a
// TARGET along one axis, allowing controlled upscale. Per role:
//   question figures -> normalize WIDTH  (tidy column, matching left/right edges)
//   option images    -> normalize HEIGHT (even a/b/c/d row)
//   inline figures   -> normalize HEIGHT (~text line height, flows inline)
const QFIG_TARGET_W_MM   = 40;  // every question figure ~ this wide
const QFIG_MAX_H_MM      = 55;  // ...unless that makes it taller than this
const OPT_TARGET_H_MM    = 18;  // every option image ~ this tall
const INLINE_TARGET_H_MM = 6.5; // inline figure height (a bit taller than the text)
const IMG_MAX_UPSCALE    = 3;   // never enlarge a low-res source beyond this factor

// Per-chapter QUESTION-figure width override (mm) — these figure types read best
// at a fixed 25mm width instead of the 40mm default. (Question figures only; the
// inline-image sizing is unaffected.)
const FIGURE_WIDTH_OVERRIDE_MM = {
  "आकृति मिलान": 25,                                 // aakriti milaan / Figure Matching
  "आकृति पूरक": 25,                                  // aakriti poorak / Figure Completion
  "रेखागणितीय चित्र पूरक (त्रिभुज, वर्ग, वृत्त)": 25,  // rekhaganitiya chitra poorak
  "आकृति निर्माण": 25,                                // aakriti nirmaan / Figure Construction
  "सन्निहित आकृतियाँ": 25,                            // sannihit aakritiyan / Embedded Figures
  // English-book chapters (fixed 25mm regardless of aspect)
  "Odd-Man-Out": 25,
  "Figure Matching": 25,
  "Geometrical Figure Completion": 25,
};
// Punched-hole chapter: 25mm ONLY when the figure is roughly square (1:1).
const PUNCHED_HOLE_CHAPTER = "पंच नियंत्रित आकृति मोड़ना, खोलना";
const SQUARE_RATIO = 1.3;    // punched-hole "approx 1:1" = aspect within ~30% either way
const EN_MA_SQUARE_RATIO = 1.2; // English Mental Ability lone-figure square tolerance (20%)

// Native (source) pixel dimensions — used for aspect-ratio decisions.
function nativeDims(filePath) {
  try {
    const cached = _imageCache.get(filePath);
    if (cached) return { width: cached.width, height: cached.height };
    return sizeOf(fs.readFileSync(filePath));
  } catch (e) {
    return null;
  }
}

// Scale to a target along `mode` ('width'|'height'); `guard` caps the OTHER
// dimension (so a normalized image never overflows), `maxUpscale` limits blur.
function targetImageDims(filePath, mode, target, guard, maxUpscale) {
  try {
    const cached = _imageCache.get(filePath);
    const buf = cached ? cached.buf : fs.readFileSync(filePath);
    const dims = cached ? { width: cached.width, height: cached.height } : sizeOf(buf);
    const w = dims.width, h = dims.height;
    let scale = mode === "width" ? target / w : target / h;
    if (maxUpscale) scale = Math.min(scale, maxUpscale);
    if (guard) {
      if (mode === "width" && h * scale > guard) scale = guard / h;
      if (mode === "height" && w * scale > guard) scale = guard / w;
    }
    return { buf, width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)) };
  } catch (e) {
    return null;
  }
}

function imageType(filePath) {
  // Trimmed images are always re-exported as PNG by preprocessImages(), regardless
  // of the source file's original extension.
  if (_imageCache.has(filePath)) return "png";
  const ext = path.extname(filePath).replace(".", "").toLowerCase();
  return ext === "jpg" || ext === "jpeg" ? "jpg" : "png";
}

// ---------- inline images embedded in text ----------
// Stage 1 rewrites in-text image references to a canonical marker "{img:/abs}".
// textToNodes() renders the surrounding text via textToRuns() (math-aware) and
// drops each referenced image onto its OWN line (a <w:br/> before and after) so
// it sits between the text, per the inline-image spec.
const _IMG_MARKER = /\{img:([^}]+)\}/g;

function inlineImageRun(p, opts) {
  // Normalize by HEIGHT so every inline figure matches the text line; width is
  // guarded so a wide one can't overflow. Flows inline with the surrounding text.
  const info = targetImageDims(p, "height", mm(INLINE_TARGET_H_MM), mm(35), IMG_MAX_UPSCALE);
  if (info) {
    return new ImageRun({ data: info.buf, transformation: { width: info.width, height: info.height }, type: imageType(p) });
  }
  return new TextRun({ text: `[image missing: ${path.basename(p)}]`, italics: true, bold: true, size: opts.size || FONT_SIZE.small, font: opts.font });
}

function textToNodes(text, opts) {
  opts = opts || {};
  const s = String(text == null ? "" : text);
  const hasImg = s.indexOf("{img:") !== -1;
  if (!hasImg && s.indexOf("\n") === -1) return textToRuns(s, opts); // fast path
  const out = [];
  // a text segment: keep math-aware runs, turn newlines into <w:br/>
  const pushText = (seg) => {
    if (!seg) return;
    seg.split("\n").forEach((line, i) => {
      if (i > 0) out.push(new TextRun({ break: 1 }));
      if (line) out.push(...textToRuns(line, opts));
    });
  };
  if (!hasImg) { pushText(s); return out; }
  // inline images flow IN the text (no line break before/after)
  let last = 0, m;
  _IMG_MARKER.lastIndex = 0;
  while ((m = _IMG_MARKER.exec(s)) !== null) {
    pushText(s.slice(last, m.index));
    out.push(inlineImageRun(m[1].trim(), opts));
    last = m.index + m[0].length;
  }
  pushText(s.slice(last));
  return out;
}

// Collect canonical inline-image paths out of a text field (for preprocessing).
function collectInlineImagePaths(text, paths) {
  if (!text) return;
  let m; _IMG_MARKER.lastIndex = 0;
  while ((m = _IMG_MARKER.exec(String(text))) !== null) paths.add(m[1].trim());
}

// Like textToNodes(), but returns an array of *Paragraphs* so each inline image
// can be a HORIZONTALLY CENTERED paragraph of its own, with the surrounding text
// as normal (left/justified) paragraphs around it. Word aligns per-paragraph, so
// centering an image on its own line requires it to be its own paragraph.
//   runOpts     - passed to textToRuns (size/font/bold/italics)
//   paraProps   - props for each TEXT paragraph (spacing/indent/keepLines/shading)
//   opts.firstParaProps - merged into the very first paragraph (e.g. list numbering)
//   opts.leadingRuns    - runs prepended to the first text paragraph (e.g. "Explanation:")
//   opts.trailingRuns   - runs appended to the last text paragraph (e.g. "[2 Marks]")
//   opts.imageParaProps - extra props merged into each centered image paragraph
function textToParagraphs(text, runOpts, paraProps, opts) {
  opts = opts || {};
  paraProps = paraProps || {};
  const s = String(text == null ? "" : text);
  const leading = opts.leadingRuns || [];
  const trailing = opts.trailingRuns || [];
  const firstProps = opts.firstParaProps || {};

  const segs = [];
  let last = 0, m; _IMG_MARKER.lastIndex = 0;
  while ((m = _IMG_MARKER.exec(s)) !== null) {
    if (m.index > last) segs.push({ img: false, v: s.slice(last, m.index) });
    segs.push({ img: true, v: m[1].trim() });
    last = m.index + m[0].length;
  }
  if (last < s.length) segs.push({ img: false, v: s.slice(last) });

  const textRuns = (seg) => {
    const runs = [];
    String(seg).split(/\n+/).forEach((line, i) => {
      if (i > 0) runs.push(new TextRun({ break: 1 }));
      runs.push(...textToRuns(line, runOpts));
    });
    return runs;
  };

  const textIdx = [];
  segs.forEach((sg, i) => { if (!sg.img && sg.v.trim() !== "") textIdx.push(i); });
  const firstTextI = textIdx.length ? textIdx[0] : -1;
  const lastTextI = textIdx.length ? textIdx[textIdx.length - 1] : -1;

  let firstApplied = false;
  const withFirst = (props) => {
    if (firstApplied) return props;
    firstApplied = true;
    return Object.assign({}, props, firstProps);
  };

  const paras = [];
  segs.forEach((sg, i) => {
    if (sg.img) {
      paras.push(new Paragraph(withFirst(Object.assign(
        { alignment: AlignmentType.CENTER, spacing: opts.imageSpacing || { before: 20, after: 20 } },
        opts.imageParaProps || {},
        { children: [inlineImageRun(sg.v, runOpts)] }
      ))));
    } else {
      if (sg.v.trim() === "") return;
      let kids = [];
      if (i === firstTextI) kids = kids.concat(leading);
      kids = kids.concat(textRuns(sg.v));
      if (i === lastTextI) kids = kids.concat(trailing);
      paras.push(new Paragraph(withFirst(Object.assign({}, paraProps, { children: kids }))));
    }
  });

  // No text paragraph existed to carry leading/trailing runs (empty text, or an
  // image-only field): emit a dedicated paragraph so they aren't lost.
  if (firstTextI === -1 && (leading.length || trailing.length || !paras.length)) {
    const p = new Paragraph(withFirst(Object.assign({}, paraProps, { children: leading.concat(trailing) })));
    if (paras.length && leading.length) paras.unshift(p); else paras.push(p);
  }
  return paras;
}

// ---------- Smart Reasoning Image Size tiers (highest priority per spec) ----------
// Classifies a Mental Ability / reasoning chapter into small/medium/large so
// question and option figures get a size proportional to how much visual
// detail the question type actually needs, instead of one fixed cap for
// every reasoning question. Chapters not in this map (arithmetic bar charts,
// etc.) are untouched — they keep the generic default cap below.
const REASONING_SIZE_TIERS = {
  // small (20-25mm question fig / 20-22mm option fig): odd-one-out, mirror image, simple comparison
  "Odd-Man-Out": "small",
  "Mirror Image": "small",
  "Figure Matching": "small",
  "भिन्न आकृति छाँटना": "small",
  "दर्पण बिंब": "small",
  "आकृति मिलान": "small",
  // medium (35-40mm question fig / 20-22mm option fig): figure series, paper folding, hidden figure
  "Figure Series Completion": "medium",
  "Punched Hole Pattern": "medium",
  "Embedded Figure": "medium",
  "आकृति शृंखला पूर्ण करना": "medium",
  "पंच नियंत्रित आकृति मोड़ना, खोलना": "medium",
  "सन्निहित आकृतियाँ": "medium",
  // large (50-60mm question fig / up to 25mm option fig): missing part, pattern completion, analogy
  "Pattern Completion": "large",
  "Geometrical Figure Completion": "large",
  "Analogy": "large",
  "आकृति पूरक": "large",
  "रेखागणितीय चित्र पूरक (त्रिभुज, वर्ग, वृत्त)": "large",
  "समानता": "large",
};
const QUESTION_FIGURE_CAP_MM = { small: 25, medium: 40, large: 60 };
const OPTION_FIGURE_CAP_MM = { small: 22, medium: 22, large: 25 };

// Per-chapter question-figure override — takes priority over the tier cap
// above. User flagged Q9-12/21-24 (both "large" tier, 60mm) as still too big
// and asked to lock them 50% smaller (30mm); applied to the exact chapters
// those questions belong to, plus their English-book equivalents for when
// this pipeline runs against that book. Option-figure size is untouched.
const QUESTION_FIGURE_OVERRIDE_MM = {
  "आकृति पूरक": 30,                                       // Figure Completion (Hindi book) — 50% of large tier's 60mm
  "रेखागणितीय चित्र पूरक (त्रिभुज, वर्ग, वृत्त)": 30,       // Geometrical Figure Completion (Hindi book) — 50% of 60mm
  "Pattern Completion": 30,                                // English-book equivalent of आकृति पूरक
  "Geometrical Figure Completion": 30,                     // English-book same-name chapter
  "सन्निहित आकृतियाँ": 19.2,                               // Embedded Figures (Hindi book) — was 16mm (40% of 40mm), increased 20% -> 19.2mm
  "Embedded Figure": 19.2,                                 // English-book equivalent
  "आकृति शृंखला पूर्ण करना": 48,                            // Figure Series Completion (Hindi book) — medium tier 40mm increased 20% -> 48mm
  "Figure Series Completion": 48,                          // English-book equivalent
  "पंच नियंत्रित आकृति मोड़ना, खोलना": 48,                  // Punched Hole Pattern (Hindi book) — medium tier 40mm increased 20% -> 48mm
  "Punched Hole Pattern": 48,                              // English-book equivalent
};

const _unclassifiedChaptersWarned = new Set();

function reasoningTierFor(chapterName) {
  if (!chapterName || !Object.prototype.hasOwnProperty.call(REASONING_SIZE_TIERS, chapterName)) return null;
  return REASONING_SIZE_TIERS[chapterName];
}

// Called only when a chapter DOES have reasoning-type images but isn't in the
// map above — flags it (once) rather than silently guessing a size, per spec.
function warnUnclassifiedReasoningChapter(chapterName) {
  if (chapterName && !_unclassifiedChaptersWarned.has(chapterName)) {
    _unclassifiedChaptersWarned.add(chapterName);
    console.warn(`[image-size] Unclassified reasoning chapter "${chapterName}" with figures — using the generic default cap; add it to REASONING_SIZE_TIERS to size it properly.`);
  }
}

function isReasoningSection(rawSectionName) {
  return rawSectionName === "MENTAL ABILITY TEST" || rawSectionName === "MENTAL ABILITY TEST (HINDI BOOK)";
}

// Resolves the small/medium/large tier for a question's figures: null for
// non-reasoning sections (arithmetic charts etc. keep the old generic cap),
// the mapped tier for known reasoning chapters, or "medium" (flagged once)
// for a reasoning chapter not yet classified.
function resolveReasoningTier(reasoningSec, chapterName) {
  if (!reasoningSec) return null;
  const tier = reasoningTierFor(chapterName);
  if (tier) return tier;
  warnUnclassifiedReasoningChapter(chapterName);
  return "medium";
}

// ---------- header (Part 1) ----------

function buildInfoParagraphs(school, font, alignment) {
  const paras = [];
  // Brand name always rendered in capitals, prominent. Session now lives in
  // the footer (alongside Date), not here.
  paras.push(new Paragraph({
    alignment,
    spacing: { after: 60 },
    children: [new TextRun({ text: (school.school || "School Name").toUpperCase(), bold: true, size: 32, font })],
  }));
  const addressLines = school.addressLines || (school.address ? [school.address] : []);
  addressLines.forEach((line, i) => {
    paras.push(new Paragraph({
      alignment,
      spacing: { after: i === addressLines.length - 1 ? 0 : 20 },
      children: [new TextRun({ text: line, size: 17, font })],
    }));
  });
  if (school.board_affiliation) {
    paras.push(new Paragraph({
      alignment,
      children: [new TextRun({ text: school.board_affiliation, size: 17, font, italics: true })],
    }));
  }
  return paras;
}

function buildHeaderTable(school, font) {
  const hasLogo = school.logo && fs.existsSync(school.logo);

  if (!hasLogo) {
    // No logo file available yet — degrade gracefully to a single centered column
    // (drop a real logo.png alongside school_config.json to activate the 2-col layout).
    return new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      borders: { ...NO_BORDERS, bottom: { style: BorderStyle.SINGLE, size: 8, color: BLACK } },
      rows: [new TableRow({
        children: [new TableCell({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          verticalAlign: VerticalAlign.CENTER,
          margins: { top: 120, bottom: 180, left: 0, right: 0 },
          children: buildInfoParagraphs(school, font, AlignmentType.CENTER),
        })],
      })],
    });
  }

  const logoColWidth = Math.round(CONTENT_WIDTH * 0.18);
  const infoColWidth = CONTENT_WIDTH - logoColWidth;
  // The 50%-smaller (0.45in) cap from the previous round was flagged as too
  // small across all 3 docs — reverted back to the pre-CBSE-overhaul default
  // (0.9in). This function is shared by the question paper, answer key, and
  // explained key, so one change here covers all three.
  const logoInfo = safeImageDims(school.logo, px(0.9), px(0.9));

  const logoCellChildren = logoInfo
    ? [new Paragraph({
        alignment: AlignmentType.LEFT,
        children: [new ImageRun({ data: logoInfo.buf, transformation: { width: logoInfo.width, height: logoInfo.height }, type: imageType(school.logo) })],
      })]
    : [new Paragraph({ children: [] })];

  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [logoColWidth, infoColWidth],
    borders: { ...NO_BORDERS, bottom: { style: BorderStyle.SINGLE, size: 8, color: BLACK } },
    rows: [new TableRow({
      children: [
        new TableCell({
          width: { size: logoColWidth, type: WidthType.DXA },
          verticalAlign: VerticalAlign.CENTER,
          margins: { top: 120, bottom: 180, left: 0, right: 120 },
          children: logoCellChildren,
        }),
        new TableCell({
          width: { size: infoColWidth, type: WidthType.DXA },
          verticalAlign: VerticalAlign.CENTER,
          margins: { top: 120, bottom: 180, left: 120, right: 0 },
          children: buildInfoParagraphs(school, font, AlignmentType.LEFT),
        }),
      ],
    })],
  });
}

// ---------- exam info block (Part 2) ----------

function distributedInfoRow(fields, font) {
  // Spreads fields (e.g. Date / Time Allowed / Maximum Marks / Total Questions)
  // edge-to-edge across the full content width, as far apart as the page allows.
  const n = fields.length;
  const colWidth = Math.floor(CONTENT_WIDTH / n);
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: fields.map(() => colWidth),
    borders: { ...NO_BORDERS, top: { style: BorderStyle.SINGLE, size: 4, color: BLACK }, bottom: { style: BorderStyle.SINGLE, size: 4, color: BLACK } },
    rows: [new TableRow({
      children: fields.map((text, i) => new TableCell({
        width: { size: colWidth, type: WidthType.DXA },
        margins: { top: 80, bottom: 80, left: i === 0 ? 0 : 40, right: i === n - 1 ? 0 : 40 },
        children: [new Paragraph({
          alignment: i === 0 ? AlignmentType.LEFT : i === n - 1 ? AlignmentType.RIGHT : AlignmentType.CENTER,
          children: [new TextRun({ text, size: 20, font })],
        })],
      })),
    })],
  });
}

// A paper counts as "Hindi" for General-Instructions translation purposes if
// any of its sections come from the Hindi book (mirrors isHindiSection()).
function isHindiPaper(data) {
  return data.sections.some((s) => isHindiSection(s.section_name));
}

function buildDynamicInstructions(data, hindi) {
  const qWord = hindi ? "\u092a\u094d\u0930\u0936\u094d\u0928" : "questions";
  const sectionList = data.sections.map((s) => `${displaySectionName(s.section_name)} (${s.questions.length} ${qWord})`).join(", ");
  const marksList = data.sections
    .map((s) => `${displaySectionName(s.section_name)}: ${Math.round(s.questions.length * MARKS_PER_QUESTION * 10) / 10} ${hindi ? "\u0905\u0902\u0915" : "marks"}`)
    .join(hindi ? "; " : "; ");
  const lines = hindi ? [
    `\u0907\u0938 \u092a\u094d\u0930\u0936\u094d\u0928\u092a\u0924\u094d\u0930 \u092e\u0947\u0902 ${data.sections.length} \u0916\u0902\u0921 \u0939\u0948\u0902 \u2014 ${sectionList} \u2014 \u0915\u0941\u0932 ${data.total_questions} \u092a\u094d\u0930\u0936\u094d\u0928 \u0939\u0948\u0902\u0964`,
    `\u092a\u094d\u0930\u0924\u094d\u092f\u0947\u0915 \u092a\u094d\u0930\u0936\u094d\u0928 \u0915\u0947 ${MARKS_PER_QUESTION} \u0905\u0902\u0915 \u0939\u0948\u0902\u0964 \u0916\u0902\u0921\u0935\u093e\u0930 \u0905\u0902\u0915: ${marksList}\u0964`,
  ] : [
    `This question paper contains ${data.sections.length} sections \u2014 ${sectionList} \u2014 ${data.total_questions} questions in all.`,
    `Each question carries ${MARKS_PER_QUESTION} marks. Section-wise marks: ${marksList}.`,
  ];
  // Only the first static instruction is kept (e.g. "read carefully...") \u2014
  // the procedural ones about attempting/submitting are dropped per request.
  const defaults = hindi ? (data.default_instructions_hindi || data.default_instructions || []) : (data.default_instructions || []);
  if (defaults[0]) lines.push(defaults[0]);
  // Explicitly-requested extra instructions (e.g. OMR filling guidance) are
  // always appended after the first default instruction, kept separate from
  // the dropped defaultInstructions boilerplate above.
  const extras = hindi ? (data.extra_instructions_hindi || data.extra_instructions || []) : (data.extra_instructions || []);
  extras.forEach((e) => lines.push(e));
  return lines;
}

function buildExamInfoBlock(data, font) {
  const maxMarks = Math.round(data.total_questions * MARKS_PER_QUESTION * 10) / 10;
  const hindi = isHindiPaper(data);

  const paras = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 120 },
      children: [new TextRun({ text: data.paper_title, bold: true, size: FONT_SIZE.mainHeading, font })],
    }),
    distributedInfoRow([
      `Time Allowed: ${data.exam_duration || "2 Hours"}`,
      `Maximum Marks: ${maxMarks}`,
      `Total Questions: ${data.total_questions}`,
    ], font),
  ];

  const instructions = buildDynamicInstructions(data, hindi);
  if (instructions.length) {
    // Spec: General Instructions block \u2014 10pt body, 1.05 line spacing, 2pt
    // after-paragraph spacing (reduces blank space vs. the old 9pt/1.4-line/3.5pt block).
    paras.push(new Paragraph({
      spacing: { before: 140, after: 40 },
      children: [new TextRun({ text: hindi ? "\u0938\u093e\u092e\u093e\u0928\u094d\u092f \u0928\u093f\u0930\u094d\u0926\u0947\u0936:" : "General Instructions:", bold: true, size: FONT_SIZE.generalInstructions, font })],
    }));
    instructions.forEach((ins, i) => {
      paras.push(new Paragraph({
        spacing: { after: 40, line: 252, lineRule: LineRuleType.AUTO },
        indent: { left: 220 },
        children: [
          new TextRun({ text: `${i + 1}. `, bold: true, size: FONT_SIZE.generalInstructions, font }),
          ...textToRuns(ins, { size: FONT_SIZE.generalInstructions, font }),
        ],
      }));
    });
  }
  return paras;
}

function buildFooter(school, data, font) {
  const parts = [];
  if (school.school) parts.push(school.school.toUpperCase());
  if (school.session) parts.push(`Session: ${school.session}`);
  parts.push(data.exam_date ? `Date: ${data.exam_date}` : "Date: ___________");
  const sep = "      |      ";
  const runs = [];
  parts.forEach((p, i) => {
    if (i > 0) runs.push(new TextRun({ text: sep, size: 17, font }));
    runs.push(new TextRun({ text: p, size: 17, font }));
  });
  runs.push(new TextRun({ text: sep, size: 17, font }));
  runs.push(new TextRun({ text: "Page ", size: 17, font }));
  runs.push(new TextRun({ children: [PageNumber.CURRENT], size: 17, font }));
  runs.push(new TextRun({ text: " of ", size: 17, font }));
  runs.push(new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 17, font }));
  return new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        border: { top: { style: BorderStyle.SINGLE, size: 4, color: BLACK } },
        spacing: { before: 80 },
        children: runs,
      }),
    ],
  });
}

// ---------- section / direction blocks (full width, Parts 4, 6, 7) ----------

// Professional ruled section separator (CBSE/JNV-booklet look):
//   ══════════════════════════════
//   SECTION A
//   MENTAL ABILITY TEST
//   Questions 1–40
//   ══════════════════════════════
// `sectionLetter`/`questionRange` are optional — omitting them (e.g. for the
// compact answer-key grid) just prints the plain ruled test name.
const RULE_BORDER = { style: BorderStyle.DOUBLE, size: 6, color: BLACK };

function sectionHeading(text, font, opts = {}) {
  const { sectionLetter, questionRange, isHindi, underline, showRule = true, ruleSpace } = opts;
  // ruleSpace (points) widens the gap between the top rule line and the
  // heading text itself — used by the explained-answer-key doc, which asked
  // for "a little spacing below the line below the title" (that title is
  // immediately followed by this section heading's own top rule).
  const topBorder = ruleSpace != null ? { ...RULE_BORDER, space: ruleSpace } : RULE_BORDER;
  const paras = [];
  if (sectionLetter) {
    // Hindi papers: "SECTION A" -> "खंड A" (word translated, letter kept Latin).
    const sectionWord = isHindi ? "खंड" : "SECTION";
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 20 },
      border: { top: RULE_BORDER },
      children: [new TextRun({ text: `${sectionWord} ${sectionLetter}`, bold: true, size: FONT_SIZE.option, font })],
    }));
  }
  paras.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: sectionLetter ? 0 : 200, after: questionRange ? 20 : 140 },
    border: sectionLetter ? undefined : (showRule ? { top: topBorder } : undefined),
    children: [new TextRun({ text, bold: true, size: FONT_SIZE.sectionHeading, font, color: BLACK, underline: underline ? {} : undefined })],
  }));
  if (questionRange) {
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 140 },
      border: { bottom: RULE_BORDER },
      children: [new TextRun({ text: `Questions ${questionRange.from}–${questionRange.to}`, italics: true, size: FONT_SIZE.small, font })],
    }));
  }
  return paras;
}

// Light-gray (5%) shaded box used for Directions — CBSE-style callout rather
// than a plain paragraph. Reading passages keep the older thin-border box
// (still allowed) instead of shading, since they're often much longer text.
const DIRECTIONS_SHADING = { type: ShadingType.PERCENT_5, fill: "FFFFFF", color: "000000" };
const PAD_6PT = 120; // 6pt of internal padding, in twips (1pt = 20 twips)

function contextBlockParagraphs(block, font, isHindi, range) {
  const isPassage = block.type === "passage";
  const isQuestionBlock = block.type === "question_block";
  // Standing preference: Hindi-book sections show "निर्देश"/"गद्यांश" instead
  // of "Directions"/"Passage" (the block's own text is already authored in Hindi).
  const label = isPassage ? (isHindi ? "गद्यांश" : "Passage") : (isHindi ? "निर्देश" : "Directions");
  const THIN = { style: BorderStyle.SINGLE, size: 4, color: BLACK };

  // For a passage / question_block, show that block's on-paper question range on
  // the same line as the label:
  //   Hindi:   "निर्देश (प्रश्न संख्या 2 से 6 तक)" / "गद्यांश (प्रश्न संख्या 2 से 6 तक)"
  //   English: "Directions (from Q. 2 to Q. 6)" / "Passage (from Q. 2 to Q. 6)"
  // Single-question blocks show just "(प्रश्न संख्या 17)" / "(Q. 17)".
  // direction blocks keep the plain "label:" form (no range).
  let headingText = label + ":";
  if ((isPassage || isQuestionBlock) && range && range.from != null) {
    let inner;
    if (isHindi) {
      inner = range.from === range.to
        ? `प्रश्न संख्या ${range.from}`
        : `प्रश्न संख्या ${range.from} से ${range.to} तक`;
    } else {
      inner = range.from === range.to
        ? `Q. ${range.from}`
        : `from Q. ${range.from} to Q. ${range.to}`;
    }
    headingText = `${label} (${inner})`;
  }

  if (isPassage) {
    // Per explicit user request: गद्यांश/Passage must never split across
    // pages — heading is keepNext-chained to the box, and the box itself is
    // an atomic cantSplit table row (same convention as a whole question).
    const heading = new Paragraph({
      spacing: { before: 200, after: 60 },
      keepNext: true,
      keepLines: true,
      children: [new TextRun({ text: headingText, bold: true, italics: true, size: FONT_SIZE.directions, font })],
    });
    // Preserve the source book's paragraph breaks: each newline-separated
    // chunk of the passage becomes its own real Paragraph (all keepLines),
    // instead of flattening the whole passage into one visual block.
    const paraTexts = String(block.text).split(/\n+/).map((t) => t.trim()).filter(Boolean);
    const bodyParas = paraTexts.map((t, i) => new Paragraph({
      spacing: { after: i === paraTexts.length - 1 ? 0 : 80 },
      keepLines: true,
      children: textToNodes(t, { size: FONT_SIZE.directions, font }),
    }));
    const boxed = new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      borders: { top: THIN, bottom: THIN, left: THIN, right: THIN, insideHorizontal: THIN, insideVertical: THIN },
      rows: [new TableRow({
        cantSplit: true,
        children: [new TableCell({
          width: { size: CONTENT_WIDTH, type: WidthType.DXA },
          margins: { top: 100, bottom: 100, left: 120, right: 120 },
          children: bodyParas,
        })],
      })],
    });
    return [heading, boxed, new Paragraph({ spacing: { after: 150 }, children: [] })];
  }

  // Directions: bold italic text in a 5%-gray shaded box with 6pt padding —
  // the shading/box is a deliberate, user-confirmed exception to the
  // otherwise-monochrome rest of the document (see feedback_cbse_formatting_v2 memory).
  // question_block shares this box layout but with NO background shading (per
  // user request) — it's a "main question" (table/graph), not a directions call-out.
  const shade = block.type === "question_block" ? undefined : DIRECTIONS_SHADING;
  const heading = new Paragraph({
    spacing: { after: 40 },
    shading: shade,
    children: [new TextRun({ text: headingText, bold: true, italics: true, size: FONT_SIZE.directions, font })],
  });
  const bodyParas = [new Paragraph({
    spacing: { after: 0 },
    shading: shade,
    // question_block body is a "main question" (table/graph) — not bold; a
    // real Directions call-out stays bold. Inline images flow within the text.
    children: textToNodes(block.text, { size: FONT_SIZE.directions, font, bold: !isQuestionBlock, italics: true }),
  })];
  const boxed = new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    borders: NO_BORDERS,
    rows: [new TableRow({
      // Bug fix: this row was missing cantSplit, so the shaded box could be
      // (and was) cut in half across a page break, leaving a bare "निर्देश:"
      // label stranded at the bottom of one page. Same atomic-row convention
      // as the passage box and every question wrapper.
      cantSplit: true,
      children: [new TableCell({
        width: { size: CONTENT_WIDTH, type: WidthType.DXA },
        shading: shade,
        margins: { top: PAD_6PT, bottom: PAD_6PT, left: PAD_6PT, right: PAD_6PT },
        children: [heading, ...bodyParas],
      })],
    })],
  });
  return [boxed, new Paragraph({ spacing: { after: 100 }, children: [] })];
}

// ---------- adaptive option layout: text/size-driven decision tree (Part 8) ----------
// IF all four options are text-only              -> single row (1x4)
// ELSE IF all four images fit within the tier's   -> single row (1x4)
//      "standard" cap (<=22mm)
// ELSE IF one option is exceptionally wide/tall   -> vertical list (4x1)
//      relative to its peers
// ELSE IF the combined row width exceeds the      -> balanced 2x2 grid
//      printable column width
// ELSE (row fits)                                 -> single row (1x4)

const CHAR_WIDTH_TWIPS = 145; // heuristic avg glyph width at 10.5pt Cambria (conservative, avoids mid-word wraps)
const OPTION_GAP_TWIPS = 300;
// Hanging indent for a question: the number sits at the left margin and the
// stem text, its wrapped lines, and the options all start at this indent.
const QUESTION_INDENT = 360; // ~0.25"
// Hanging indent WITHIN an option: the "a)"/"b)" marker hangs to the left and
// the option text (incl. wrapped lines) aligns to the right of it.
const OPTION_INDENT = 260; // ~0.18"

// Bounding box (px) an option image is scaled into for a given reasoning
// tier — null tier (non-reasoning sections) keeps the old generic ~21.6mm cap.
function optionImageCapPx(tier) {
  const capMm = tier ? OPTION_FIGURE_CAP_MM[tier] : 21.6;
  return mm(capMm);
}

// Option figures normalize by HEIGHT (even a/b/c/d row), width guarded so a wide
// one can't overflow its cell. Controlled upscale lifts low-res sources.
function optionImageDims(imgPath) {
  return targetImageDims(imgPath, "height", mm(OPT_TARGET_H_MM), mm(24), IMG_MAX_UPSCALE);
}

function estimateOptionWidth(opt, tier) {
  if (opt.image) {
    const info = optionImageDims(opt.image);
    return info ? pxToTwips(info.width) + 260 : 900;
  }
  const len = (opt.label ? opt.label.length + 3 : 0) + (opt.text ? opt.text.length : 0);
  return len * CHAR_WIDTH_TWIPS;
}

function estimateOptionHeight(opt, tier) {
  if (opt.image) {
    const info = optionImageDims(opt.image);
    return info ? pxToTwips(info.height) : 400;
  }
  return 260; // ~one text line
}

function chooseOptionLayout(options, availableWidth, tier, forceRow) {
  if (forceRow && options.length === 4) return "1x4"; // experiment: mental-ability one-row
  if (options.length !== 4) return options.length > 2 ? "4x1" : "1x4";

  const widths = options.map((o) => estimateOptionWidth(o, tier));
  const heights = options.map((o) => estimateOptionHeight(o, tier));
  const rowTotal = widths.reduce((a, b) => a + b, 0) + OPTION_GAP_TWIPS * 3;
  const maxW = Math.max(...widths);
  const sortedW = [...widths].sort((a, b) => a - b);
  const sortedH = [...heights].sort((a, b) => a - b);
  const medW = sortedW[Math.floor(sortedW.length / 2)];
  const medH = sortedH[Math.floor(sortedH.length / 2)];

  const allTextOnly = options.every((o) => !o.image);
  const capMm = tier ? OPTION_FIGURE_CAP_MM[tier] : 21.6;
  const allImagesStandardSize = options.every((o) => !o.image) || capMm <= 22;

  // Rule 1/2: text-only, or every image already at/under the ~22mm standard
  // size for its tier — a single row whenever it actually fits.
  if ((allTextOnly || allImagesStandardSize) && rowTotal <= availableWidth) return "1x4";

  // Rule 4: one option exceptionally wide or tall vs. its peers -> vertical list,
  // rather than forcing it into a lopsided 2x2 grid.
  const exceptional = (medW > 0 && maxW > medW * 1.6) || (medH > 0 && Math.max(...heights) > medH * 1.6);
  if (exceptional) return "4x1";

  // Row still fits regardless of the above -> keep it compact.
  if (rowTotal <= availableWidth) return "1x4";

  // Rule 3: combined width exceeds the printable column -> balanced 2x2.
  const halfWidth = (availableWidth - OPTION_GAP_TWIPS) / 2;
  if (maxW <= halfWidth) return "2x2";

  return "4x1";
}

function optionCellContent(opt, font, keepNext, optRef, tier) {
  const numbering = optRef ? { reference: optRef, level: 0 } : undefined;
  if (opt.image) {
    const info = optionImageDims(opt.image);
    const paras = [];
    if (info) {
      paras.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 20 },
        keepNext: true, // image always stays with its own label below it
        keepLines: true,
        children: [new ImageRun({ data: info.buf, transformation: { width: info.width, height: info.height }, type: imageType(opt.image) })],
      }));
    } else {
      paras.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        keepNext: true,
        children: [new TextRun({ text: `[image missing: ${path.basename(opt.image)}]`, italics: true, bold: true, size: FONT_SIZE.small, font })],
      }));
    }
    // Label always centered directly below the image (Part 8 / user request)
    // — real numPr list marker (a), b), ...) rather than a typed "(a)" run.
    paras.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      keepNext,
      keepLines: true,
      numbering,
      children: [],
    }));
    return paras;
  }
  return [new Paragraph({
    keepNext,
    keepLines: true,
    numbering,
    // hanging indent: the a)/b) marker hangs back to the cell's left edge,
    // wrapped option text lines up under the text (not under the marker).
    indent: { left: OPTION_INDENT, hanging: OPTION_INDENT },
    children: textToNodes(opt.text || "", { size: FONT_SIZE.option, font }),
  })];
}

function optionsBlock(options, availableWidth, font, optRef, tier, indent = 0, forceRow = false) {
  // Shift the whole options grid right by `indent` to line up under the stem
  // text; shrink the content width by the same amount so it stays in the column.
  const tableIndent = indent ? { size: indent, type: WidthType.DXA } : undefined;
  availableWidth = availableWidth - indent;
  const layout = chooseOptionLayout(options, availableWidth, tier, forceRow);

  // A multi-row option table (2x2 / 4x1) must never split between rows —
  // every row except the last is chained to the next via keepNext so Word
  // moves the whole remaining block together rather than breaking mid-way
  // through a question's options (only the last row may release the chain,
  // allowing the *next question* to start fresh in whichever column/page
  // has room).
  if (layout === "1x4" || (layout !== "2x2" && layout !== "4x1")) {
    const colW = Math.floor(availableWidth / options.length);
    const row = new TableRow({
      cantSplit: true,
      children: options.map((opt) => new TableCell({
        width: { size: colW, type: WidthType.DXA },
        margins: { top: 30, bottom: 30, left: 60, right: 60 },
        children: optionCellContent(opt, font, false, optRef, tier),
      })),
    });
    return new Table({ width: { size: availableWidth, type: WidthType.DXA }, indent: tableIndent, columnWidths: options.map(() => colW), borders: NO_BORDERS, rows: [row] });
  }

  if (layout === "4x1") {
    const rows = options.map((opt, i) => new TableRow({
      cantSplit: true,
      children: [new TableCell({
        width: { size: availableWidth, type: WidthType.DXA },
        margins: { top: 20, bottom: 20, left: 60, right: 60 },
        children: optionCellContent(opt, font, i < options.length - 1, optRef, tier),
      })],
    }));
    return new Table({ width: { size: availableWidth, type: WidthType.DXA }, indent: tableIndent, columnWidths: [availableWidth], borders: NO_BORDERS, rows });
  }

  // 2x2 — balanced, equal-width columns, equal gutter
  const half = Math.floor((availableWidth - OPTION_GAP_TWIPS) / 2);
  const rows = [];
  const numRows = Math.ceil(options.length / 2);
  for (let i = 0; i < options.length; i += 2) {
    const isLastRow = i / 2 === numRows - 1;
    const left = options[i], right = options[i + 1];
    rows.push(new TableRow({
      cantSplit: true,
      children: [
        new TableCell({ width: { size: half, type: WidthType.DXA }, margins: { top: 30, bottom: 30, left: 60, right: OPTION_GAP_TWIPS / 2 }, children: optionCellContent(left, font, !isLastRow, optRef, tier) }),
        right
          ? new TableCell({ width: { size: half, type: WidthType.DXA }, margins: { top: 30, bottom: 30, left: OPTION_GAP_TWIPS / 2, right: 60 }, children: optionCellContent(right, font, !isLastRow, optRef, tier) })
          : new TableCell({ width: { size: half, type: WidthType.DXA }, children: [new Paragraph({ children: [] })] }),
      ],
    }));
  }
  return new Table({ width: { size: availableWidth, type: WidthType.DXA }, indent: tableIndent, columnWidths: [half, half], borders: NO_BORDERS, rows });
}

// ---------- one question's content (Parts 3, 5, 8) ----------
// Emitted directly into a real 2-column Word section (see
// collectBodyBlocks/buildQuestionPaperDoc) \u2014 content flows independently
// per column instead of being locked to a shared table row, so a short
// question doesn't force its column partner to start at the same line (the
// gap the user flagged around Q4/Q10-Q12).
//
// keepNext chains between mixed Paragraph/Table content are not reliably
// honored across a column break by every renderer (verified: LibreOffice
// can still split a question's stem from its own image/options that way).
// So the whole question \u2014 stem, figure, options \u2014 is wrapped in a single,
// borderless, one-row/one-cell table with cantSplit: true. A table row that
// cannot split is a much stronger guarantee: the entire question moves to
// the next column/page as one unit rather than breaking mid-way.

function renderQuestionInline(q, availableWidth, font, reasoningSec) {
  const nodes = [];
  // Smart Reasoning Image Size tier for this question's chapter (null for
  // non-reasoning sections, which keep the old generic image cap).
  const tier = resolveReasoningTier(reasoningSec, q._chapter_name);

  // Marks + PYQ tag: kept together as ONE non-breaking unit (NB-spaces so it can
  // never split across lines). The "[N Marks]" part is optional per paper
  // (_showQuestionMarks); the PYQ tag is only ever the year, in light gray,
  // never the exam name. (Right-aligned onto the stem's last line just below.)
  const NB = "\u00a0";
  const metaRuns = [];
  if (_showQuestionMarks) {
    metaRuns.push(new TextRun({ text: `[${MARKS_PER_QUESTION}${NB}Marks]`, italics: true, size: FONT_SIZE.small, font }));
  }
  if (q.is_pyq && q.pyq_year) {
    const sep = metaRuns.length ? NB + NB : "";
    metaRuns.push(new TextRun({ text: `${sep}PYQ${NB}\u2022${NB}${q.pyq_year}`, italics: true, size: FONT_SIZE.small, font, color: "808080" }));
  }

  // Real numPr list marker ("1.") started at the exact display_number Stage 1
  // resolved (honors continuous/per_section numbering) \u2014 not a typed "Q1. "
  // text run, per the "Question numbering" formatting spec.
  // Right tab stop near the column's right edge; the trailing runs start with a
  // Tab so the marks jump there — on the SAME line as the stem, flush right,
  // never on a line of their own. Positioned back by the indent so it can't
  // overshoot the column (which would wrap the tag).
  const stemTrailing = metaRuns.length ? [new TextRun({ children: [new Tab()] }), ...metaRuns] : [];
  const rightTab = metaRuns.length
    ? { tabStops: [{ type: TabStopType.RIGHT, position: availableWidth }] }  // flush to the column's right edge
    : {};

  // Stem: ONE numbered paragraph. Inline {img:} figures flow within the text
  // (textToNodes handles inline images + newlines); the "1." hangs to the left
  // margin, text at the indent; marks/PYQ trail on the same line via the tab.
  const stemRuns = textToNodes(q.question_text || "", { size: FONT_SIZE.question, font });
  const qNumRef = registerQuestionNumbering(q.display_number);
  nodes.push(new Paragraph(Object.assign({
    numbering: { reference: qNumRef, level: 0 },
    indent: { left: QUESTION_INDENT, hanging: QUESTION_INDENT },
    spacing: { after: 40 },
    children: stemRuns.concat(stemTrailing),
  }, rightTab)));

  if (q.question_images && q.question_images.length > 0) {
    // Normalize question figures by WIDTH so every one is the same width across
    // the paper (height follows aspect ratio, guarded so a tall one can't run
    // away). Controlled upscale lifts low-res sources up to the target. Some
    // chapters override the width to 25mm; the punched-hole chapter only does so
    // when its figure is roughly square. Stays centered in the column.
    let targetWmm = FIGURE_WIDTH_OVERRIDE_MM[q._chapter_name] || QFIG_TARGET_W_MM;
    if (q._chapter_name === PUNCHED_HOLE_CHAPTER) {
      const nd = nativeDims(q.question_images[0]);
      if (nd && nd.height > 0) {
        const aspect = nd.width / nd.height;
        if (aspect <= SQUARE_RATIO && aspect >= 1 / SQUARE_RATIO) targetWmm = 25;
      }
    }
    // English Mental Ability: a question with a single ~square figure (1:1 ±20%)
    // renders at 25mm wide.
    if (_paperLanguage === "english" && reasoningSec && q.question_images.length === 1) {
      const nd = nativeDims(q.question_images[0]);
      if (nd && nd.height > 0) {
        const aspect = nd.width / nd.height;
        if (aspect <= EN_MA_SQUARE_RATIO && aspect >= 1 / EN_MA_SQUARE_RATIO) targetWmm = 25;
      }
    }
    const info = targetImageDims(q.question_images[0], "width", mm(targetWmm), mm(QFIG_MAX_H_MM), IMG_MAX_UPSCALE);
    const p = info
      ? new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 30 }, children: [new ImageRun({ data: info.buf, transformation: { width: info.width, height: info.height }, type: imageType(q.question_images[0]) })] })
      : new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: `[image missing: ${path.basename(q.question_images[0])}]`, italics: true, bold: true, size: FONT_SIZE.small, font })] });
    nodes.push(p);
  }

  // Fresh option-letter list per question so it always restarts at "a)".
  const optRef = registerOptionNumbering();
  nodes.push(optionsBlock(q.options, availableWidth, font, optRef, tier, QUESTION_INDENT, reasoningSec && _forceMA1x4));

  // Wrap the whole question in an atomic single-cell table so it can never
  // split between column/page breaks. Tighter margins than before (reduces
  // blank space per the page-density goal) \u2014 still enough breathing room
  // between adjacent questions to stay readable.
  const wrapper = new Table({
    width: { size: availableWidth, type: WidthType.DXA },
    columnWidths: [availableWidth],
    borders: NO_BORDERS,
    rows: [new TableRow({
      cantSplit: true,
      children: [new TableCell({
        width: { size: availableWidth, type: WidthType.DXA },
        margins: { top: 60, bottom: 40, left: 0, right: 0 },
        children: nodes,
      })],
    })],
  });
  return [wrapper];
}

// ---------- Parts 6/7/11: real 2-column section flow with full-width breakouts ----------

const QUESTION_COL_WIDTH = COL_WIDTH - 140; // small safety margin inside each native column

function collectBodyBlocks(data, font) {
  // Returns an ordered array of { mode: "full" | "col2", nodes: [...] }.
  // Consecutive same-mode blocks are merged by the caller into one Word
  // section, so directions/passages/section headings always span full
  // width and questions always flow in two real columns.
  const blocks = [];
  // pendingBreak forces the NEXT pushed block to begin a fresh Word section
  // even if it has the same column mode (used to close off a question_block's
  // sub-questions — see the boundary logic in the question loop below).
  let pendingBreak = false;
  const push = (mode, nodes) => {
    const blk = { mode, nodes };
    if (pendingBreak) { blk.startNewSection = true; pendingBreak = false; }
    blocks.push(blk);
  };
  const pushFull = (nodes) => push("full", nodes);
  const pushCol2 = (nodes) => push("col2", nodes);

  // Range of on-paper (display) question numbers per context block — used to
  // print "Directions (Q. 17 - Q. 22)" / "गद्यांश (प्रश्न 17 - प्रश्न 22)" in
  // the block heading. A block's questions are contiguous (Stage 1 orders them).
  const blockRange = {};
  for (const sec of data.sections) {
    for (const q of sec.questions) {
      if (q.context_block_id != null && q.display_number != null) {
        const r = blockRange[q.context_block_id];
        if (!r) blockRange[q.context_block_id] = { from: q.display_number, to: q.display_number };
        else { r.from = Math.min(r.from, q.display_number); r.to = Math.max(r.to, q.display_number); }
      }
    }
  }

  data.sections.forEach((sec, secIdx) => {
    const questionRange = sec.questions.length
      ? { from: sec.questions[0].display_number, to: sec.questions[sec.questions.length - 1].display_number }
      : null;
    const hindiSec = isHindiSection(sec.section_name);
    pushFull(sectionHeading(displaySectionName(sec.section_name), font, {
      sectionLetter: String.fromCharCode(65 + secIdx),
      questionRange,
      isHindi: hindiSec,
    }));
    const reasoningSec = isReasoningSection(sec.section_name);
    let lastChapter = null;
    // RULE: all questions in the same chapter share ONE set of directions.
    // Only the first "direction"-type block encountered in a chapter is ever
    // printed; every later question in that chapter — even if its own
    // context_block_id differs (e.g. a lettered-options vs numbered-options
    // variant of the same "odd one out" task) — is treated as already
    // covered and doesn't get a restated direction. This does NOT apply to
    // "passage"-type blocks: each reading passage is genuinely distinct
    // content and must still appear once, right before its own questions.
    let chapterDirectionShown = false;
    let seenDistinctBlocks = new Set();
    sec.questions.forEach((q, qi) => {
      if (q._chapter_name !== lastChapter) {
        chapterDirectionShown = false;
        lastChapter = q._chapter_name;
      }
      if (q.context_block_id) {
        const block = data.context_blocks[q.context_block_id];
        // "passage" and "question_block" are DISTINCT blocks: each is unique
        // content (a reading passage, or a shared table/graph "main question")
        // and must be printed once, right before its own group of questions —
        // unlike "direction", a shared instruction printed once per chapter.
        const isDistinct = block && (block.type === "passage" || block.type === "question_block");
        const alreadyCovered = isDistinct ? seenDistinctBlocks.has(q.context_block_id) : chapterDirectionShown;
        if (!alreadyCovered) {
          if (block) pushFull(contextBlockParagraphs(block, font, hindiSec, blockRange[q.context_block_id]));
          if (isDistinct) seenDistinctBlocks.add(q.context_block_id);
          else chapterDirectionShown = true;
        }
      }
      pushCol2(renderQuestionInline(q, QUESTION_COL_WIDTH, font, reasoningSec));

      // question_block ONLY: after its LAST sub-question, force a (continuous)
      // section break so the block's sub-questions form their own self-contained
      // 2-column region and the following questions begin fresh below — they
      // don't merge into the same column flow. (Sub-questions are contiguous.)
      const qBlock = q.context_block_id ? data.context_blocks[q.context_block_id] : null;
      if (qBlock && qBlock.type === "question_block") {
        const next = sec.questions[qi + 1];
        if (!next || next.context_block_id !== q.context_block_id) pendingBreak = true;
      }
    });
  });
  return blocks;
}

// ---------- document builders ----------

function buildQuestionPaperDoc(data, school) {
  const font = school.displayFont || "Georgia";
  // Per-paper option: hide the "[N Marks]" tag on every question when false.
  _showQuestionMarks = data.show_question_marks !== false;
  // Per-paper option: force Mental Ability questions into a single 1x4 option row.
  _forceMA1x4 = data.mental_ability_1x4 === true;
  _paperLanguage = data.language || null;

  // Fresh numPr numbering-definition collector for this document — every
  // question number and option-letter list registered while building the
  // body gets appended here, then attached to the Document itself below.
  _numberingConfig = [];
  _numRefCounter = 0;

  const headerBlock = { mode: "full", nodes: [buildHeaderTable(school, font), ...buildExamInfoBlock(data, font)] };
  const bodyBlocks = collectBodyBlocks(data, font);

  // Merge consecutive same-mode blocks into contiguous runs — each run
  // becomes one real Word section, alternating single-column (headers,
  // section titles, directions, passages) and two-column (the questions
  // themselves) layout.
  const runs = [{ mode: headerBlock.mode, nodes: [...headerBlock.nodes] }];
  for (const b of bodyBlocks) {
    const last = runs[runs.length - 1];
    // b.startNewSection forces a fresh section even when the column mode matches
    // (closes off a question_block's sub-questions from the following questions).
    if (last.mode === b.mode && !b.startNewSection) last.nodes.push(...b.nodes);
    else runs.push({ mode: b.mode, nodes: [...b.nodes] });
  }

  const docSections = runs.map((run) => ({
    properties: {
      page: PAGE_SETUP,
      type: SectionType.CONTINUOUS,
      column: run.mode === "col2"
        ? { count: 2, space: COL_GUTTER, separate: true, equalWidth: true }
        : { count: 1 },
    },
    headers: { default: buildWatermarkHeader(font) },
    footers: { default: buildFooter(school, data, font) },
    children: run.nodes,
  }));

  return new Document({
    numbering: { config: _numberingConfig },
    styles: { default: { document: { run: { font } } } },
    sections: docSections,
  });
}

function buildAnswerKeyDoc(data, school) {
  const font = school.displayFont || "Georgia";
  const children = [
    buildHeaderTable(school, font),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 260 }, // a bit more room before the first section heading
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLACK } }, // single rule line under the title
      children: [new TextRun({ text: `${data.paper_title} — Answer Key`, bold: true, size: FONT_SIZE.mainHeading, font })],
    }),
  ];
  const PAIRS_PER_ROW = 4;
  for (const sec of data.sections) {
    // Answer key: underlined section heading, no top rule border (per explicit request).
    children.push(...sectionHeading(displaySectionName(sec.section_name), font, { underline: true, showRule: false }));
    const qs = sec.questions;
    const colWidth = CONTENT_WIDTH / (PAIRS_PER_ROW * 2);
    const rows = [];
    for (let i = 0; i < qs.length; i += PAIRS_PER_ROW) {
      const cells = [];
      for (let j = 0; j < PAIRS_PER_ROW; j++) {
        const q = qs[i + j];
        cells.push(new TableCell({
          width: { size: colWidth, type: WidthType.DXA },
          margins: { top: 60, bottom: 60, left: 100, right: 60 },
          children: [new Paragraph({ children: [new TextRun({ text: q ? `Q${q.display_number}` : "", bold: true, size: 18, font })] })],
        }));
        cells.push(new TableCell({
          width: { size: colWidth, type: WidthType.DXA },
          margins: { top: 60, bottom: 60, left: 60, right: 100 },
          children: [new Paragraph({ children: [new TextRun({ text: q ? `(${q.correct_answer || "?"})` : "", size: 18, font })] })],
        }));
      }
      rows.push(new TableRow({ cantSplit: true, children: cells }));
    }
    children.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: Array(PAIRS_PER_ROW * 2).fill(colWidth),
      borders: {
        top: { style: BorderStyle.SINGLE, size: 2, color: BLACK },
        bottom: { style: BorderStyle.SINGLE, size: 2, color: BLACK },
        left: { style: BorderStyle.SINGLE, size: 2, color: BLACK },
        right: { style: BorderStyle.SINGLE, size: 2, color: BLACK },
        insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: BLACK },
        insideVertical: { style: BorderStyle.SINGLE, size: 2, color: BLACK },
      },
      rows,
    }));
  }
  return new Document({
    styles: { default: { document: { run: { font } } } },
    sections: [{ properties: { page: PAGE_SETUP }, headers: { default: buildWatermarkHeader(font) }, footers: { default: buildFooter(school, data, font) }, children }],
  });
}

// Splits an explanation into individual working steps. Steps are authored
// in the DB separated by newlines (optionally prefixed "Step N:"); a plain
// single-line explanation (no newlines) still renders as one line, same as
// before — this only changes behavior for multi-step text.
function explanationSteps(text) {
  return (text || "(not available)")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function renderExplanationInline(q, availableWidth, font) {
  const nodes = [];
  const statusTag = q.answer_status && q.answer_status !== "resolved"
    ? new TextRun({ text: `  [${q.answer_status}]`, italics: true, bold: true, size: 16, font })
    : new TextRun({ text: "" });

  nodes.push(new Paragraph({
    spacing: { after: 40 },
    children: [
      new TextRun({ text: `Q${q.display_number}. `, bold: true, size: 20, font }),
      new TextRun({ text: `Answer: (${q.correct_answer || "unresolved"})`, bold: true, size: 20, font }),
      statusTag,
    ],
  }));

  const steps = explanationSteps(q.explanation);
  const explLead = [new TextRun({ text: "Explanation:", bold: true, italics: true, size: 18, font })];
  if (steps.length <= 1) {
    // "Explanation: <text>" on one line; inline images flow within the text.
    nodes.push(new Paragraph({
      spacing: { after: 90 },
      children: explLead
        .concat([new TextRun({ text: " ", size: 18, font })])
        .concat(textToNodes(steps[0] || "", { size: 18, font })),
    }));
  } else {
    nodes.push(new Paragraph({ spacing: { after: 30 }, children: explLead }));
    steps.forEach((step, i) => {
      nodes.push(new Paragraph({
        spacing: { after: i === steps.length - 1 ? 90 : 50 },
        indent: { left: 220 },
        children: textToNodes(step, { size: 18, font }),
      }));
    });
  }

  // Wrap the whole answer+explanation block in an atomic single-cell table
  // so a multi-step solution never gets split mid-way across a column or
  // page break — same convention as the question-paper renderer.
  const wrapper = new Table({
    width: { size: availableWidth, type: WidthType.DXA },
    columnWidths: [availableWidth],
    borders: NO_BORDERS,
    rows: [new TableRow({
      cantSplit: true,
      children: [new TableCell({
        width: { size: availableWidth, type: WidthType.DXA },
        margins: { top: 100, bottom: 60, left: 0, right: 0 },
        children: nodes,
      })],
    })],
  });
  return [wrapper];
}

function collectExplainedBodyBlocks(data, font) {
  const blocks = [];
  for (const sec of data.sections) {
    // Explained key: underlined section heading, keeps its top rule border
    // (only the plain answer key had the border removed).
    // ruleSpace widens the gap between the top rule line and the heading
    // text — the title ("...Answer Key with Explanations") sits right above
    // this first section heading's own rule line.
    blocks.push({ mode: "full", nodes: sectionHeading(displaySectionName(sec.section_name), font, { underline: true, ruleSpace: 6 }) });
    for (const q of sec.questions) {
      blocks.push({ mode: "col2", nodes: renderExplanationInline(q, QUESTION_COL_WIDTH, font) });
    }
  }
  return blocks;
}

function buildAnswerKeyExplainedDoc(data, school) {
  const font = school.displayFont || "Georgia";

  const headerBlock = {
    mode: "full",
    nodes: [
      buildHeaderTable(school, font),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 200, after: 200 },
        children: [new TextRun({ text: `${data.paper_title} — Answer Key with Explanations`, bold: true, size: FONT_SIZE.mainHeading, font })],
      }),
    ],
  };
  const bodyBlocks = collectExplainedBodyBlocks(data, font);

  // Same alternating full-width / two-column run merging as the question
  // paper, so section headings span the page while Q&A blocks flow through
  // a genuine two-column section with the vertical rule separator.
  const runs = [{ mode: headerBlock.mode, nodes: [...headerBlock.nodes] }];
  for (const b of bodyBlocks) {
    const last = runs[runs.length - 1];
    // b.startNewSection forces a fresh section even when the column mode matches
    // (closes off a question_block's sub-questions from the following questions).
    if (last.mode === b.mode && !b.startNewSection) last.nodes.push(...b.nodes);
    else runs.push({ mode: b.mode, nodes: [...b.nodes] });
  }

  const docSections = runs.map((run) => ({
    properties: {
      page: PAGE_SETUP,
      type: SectionType.CONTINUOUS,
      column: run.mode === "col2"
        ? { count: 2, space: COL_GUTTER, separate: true, equalWidth: true }
        : { count: 1 },
    },
    headers: { default: buildWatermarkHeader(font) },
    footers: { default: buildFooter(school, data, font) },
    children: run.nodes,
  }));

  return new Document({
    styles: { default: { document: { run: { font } } } },
    sections: docSections,
  });
}

// ---------- main ----------

async function main() {
  const args = process.argv.slice(2);
  const jsonPath = args[0];
  let outdir = ".", prefix = null, schoolConfigPath = path.join(__dirname, "school_config.json");
  for (let i = 1; i < args.length; i++) {
    if (args[i] === "--outdir") outdir = args[++i];
    if (args[i] === "--prefix") prefix = args[++i];
    if (args[i] === "--school-config") schoolConfigPath = args[++i];
  }
  if (!jsonPath) {
    console.error("Usage: node build_docx.js paper_content.json --outdir ./out --prefix name --school-config school_config.json");
    process.exit(1);
  }
  const data = JSON.parse(fs.readFileSync(jsonPath, "utf8"));
  let school = { school: "School Name", displayFont: "Georgia", defaultInstructions: [] };
  if (fs.existsSync(schoolConfigPath)) {
    school = JSON.parse(fs.readFileSync(schoolConfigPath, "utf8"));
    if (school.logo && !path.isAbsolute(school.logo)) {
      school.logo = path.join(path.dirname(schoolConfigPath), school.logo);
    }
  }
  data.default_instructions = school.defaultInstructions || [];
  data.extra_instructions = school.extraInstructions || [];
  data.default_instructions_hindi = school.defaultInstructionsHindi || [];
  data.extra_instructions_hindi = school.extraInstructionsHindi || [];

  if (!prefix) prefix = data.output_name || "question_paper";
  if (!fs.existsSync(outdir)) fs.mkdirSync(outdir, { recursive: true });

  // Trim transparent/uniform margins off every question/option image (and the
  // logo) once, up front, so the rest of the (synchronous) render code can
  // just look sizes up — see preprocessImages()/_imageCache above.
  await preprocessImages(data, school);
  await prepareWatermark(school);

  const qDoc = buildQuestionPaperDoc(data, school);
  const akDoc = buildAnswerKeyDoc(data, school);
  const akeDoc = buildAnswerKeyExplainedDoc(data, school);

  const outQ = path.join(outdir, `${prefix}_question_paper.docx`);
  const outAK = path.join(outdir, `${prefix}_answer_key.docx`);
  const outAKE = path.join(outdir, `${prefix}_answer_key_explained.docx`);

  fs.writeFileSync(outQ, await Packer.toBuffer(qDoc));
  fs.writeFileSync(outAK, await Packer.toBuffer(akDoc));
  fs.writeFileSync(outAKE, await Packer.toBuffer(akeDoc));

  console.log("Wrote:");
  console.log(" ", outQ);
  console.log(" ", outAK);
  console.log(" ", outAKE);
}

main().catch((e) => { console.error(e); process.exit(1); });
