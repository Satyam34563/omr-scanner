/**
 * build_html.js — CBSE Stage 2a: cbse_paper_content.json -> a single self-contained
 * HTML file with all LaTeX rendered by KaTeX. A separate weasyprint pass turns
 * that HTML into the PDF (see cli/cbse_pdf.py).
 *
 *   node build_html.js --content cbse_paper_content.json \
 *       --image-base /path/to/question_bank_i_to_viii --out paper.html
 *
 * Math: inline $...$ and display $$...$$ spans in the *_latex fields are rendered
 * to HTML by KaTeX; the KaTeX stylesheet is inlined with its font URLs rewritten
 * to absolute paths so weasyprint can find them offline.
 */
const fs = require("fs");
const path = require("path");
const katex = require("katex");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : def;
}

const contentPath = arg("content");
const imageBase = arg("image-base", "");
const outPath = arg("out");
if (!contentPath || !outPath) {
  console.error("usage: node build_html.js --content x.json --image-base DIR --out paper.html");
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(contentPath, "utf8"));

// School branding (logo + name + address) — same source as the competitive papers.
const schoolCfgPath = arg("school-config", path.join(imageBase, "school_config.json"));
let school = {};
try { school = JSON.parse(fs.readFileSync(schoolCfgPath, "utf8")); } catch (e) { school = {}; }
const schoolDir = path.dirname(schoolCfgPath);

// Absolute logo path (header + optional page watermark)
let logoAbs = "";
if (school.logo) {
  const lp = path.isAbsolute(school.logo) ? school.logo : path.join(schoolDir, school.logo);
  if (fs.existsSync(lp)) logoAbs = lp;
}

// "2026-08-10" -> "10 Aug 2026" (falls back to the raw string)
function fmtDate(s) {
  if (!s) return "";
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return String(s);
  const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return parseInt(m[3], 10) + " " + MON[parseInt(m[2], 10) - 1] + " " + m[1];
}

// ---- KaTeX CSS with absolute font paths (so weasyprint resolves them) ----
const katexDist = path.join(__dirname, "node_modules", "katex", "dist");
let katexCss = fs.readFileSync(path.join(katexDist, "katex.min.css"), "utf8");
katexCss = katexCss.replace(/url\((fonts\/[^)]+)\)/g, (_m, p) => `url(file://${path.join(katexDist, p)})`);

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Escape, but keep the source's inline emphasis: HTML tags (<b>/<i>/<u>/<sup>/
// <sub>/<br>) AND markdown (**bold** / *italic*) — the question text uses both
// (e.g. "<b>not</b>" and "**not**") to emphasise words like "not".
function escText(s) {
  s = esc(s);
  s = s.replace(/&lt;(\/?(?:b|i|u|sup|sub|br)\s*\/?)&gt;/gi, "<$1>"); // whitelisted HTML tags
  s = s.replace(/\*\*([^*]+?)\*\*/g, "<b>$1</b>");                    // **bold**
  s = s.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<i>$2</i>");      // *italic* (single, not **)
  return s;
}

// Render a mixed prose + $...$ / $$...$$ string to HTML.
const MATH_RE = /\$\$([\s\S]+?)\$\$|\$([^$]+?)\$/g;
function renderLatex(text) {
  const s = String(text == null ? "" : text);
  if (s.indexOf("$") === -1) return escText(s);
  let out = "", last = 0, m;
  MATH_RE.lastIndex = 0;
  while ((m = MATH_RE.exec(s)) !== null) {
    out += escText(s.slice(last, m.index));
    const display = m[1] != null;
    // KaTeX's math fonts have no ₹ glyph -> render it as "Rs." inside math.
    const tex = (display ? m[1] : m[2]).replace(/₹/g, "\\text{Rs.}\\,");
    try {
      out += katex.renderToString(tex, { throwOnError: false, displayMode: display, strict: false, trust: true });
    } catch (e) {
      out += `<span style="color:#c00">${esc(tex)}</span>`;
    }
    last = m.index + m[0].length;
  }
  out += escText(s.slice(last));
  return out;
}

function imgTag(rel) {
  if (!rel) return "";
  const abs = path.isAbsolute(rel) ? rel : path.join(imageBase, rel);
  return `<img class="qimg" src="file://${abs}" alt="">`;
}

function questionImages(q) {
  let arr = [];
  try { arr = q.question_images ? JSON.parse(q.question_images) : []; } catch (e) { arr = []; }
  return arr.map(imgTag).join("");
}

function optionsHtml(q) {
  if (!q.options || !q.options.length) return "";
  const items = q.options.map((o) => {
    const body = o.image ? imgTag(o.image) : renderLatex(o.text_latex || o.text || "");
    return `<span class="opt"><b>(${esc(o.label)})</b> ${body}</span>`;
  }).join("");
  return `<div class="opts">${items}</div>`;
}

function questionHtml(q) {
  const stem = renderLatex(q.question_latex || q.question_text || "");
  const marks = (data.show_question_marks !== false && q.section_marks != null)
    ? `<span class="marks">[${q.section_marks}]</span>` : "";
  return `<div class="q">
    <div class="qhead"><span class="qno">${q.display_number}.</span>
      <div class="qbody">${stem}${marks}${questionImages(q)}${optionsHtml(q)}</div>
    </div></div>`;
}

function sectionHtml(sec) {
  let html = "";
  if (sec.title) html += `<h2 class="sec">${esc(sec.title)}</h2>`;
  if (sec.instruction) html += `<p class="secnote">${esc(sec.instruction)}</p>`;
  if (sec.intact_blocks) {
    // group consecutive questions by their case block; render the case once
    let curCb = undefined;
    sec.questions.forEach((q) => {
      if (q.context_block_id !== curCb) {
        curCb = q.context_block_id;
        const cb = data.context_blocks[String(curCb)];
        if (cb) html += `<div class="case">${renderLatex(cb.text_latex || cb.text || "")}${imgTag(cb.image)}</div>`;
      }
      html += questionHtml(q);
    });
  } else {
    sec.questions.forEach((q) => { html += questionHtml(q); });
  }
  return html;
}

// ---- section summary (for the general-instructions block) ----
function sectionSummary() {
  var order = [], by = {};
  data.sections.forEach(function (s) {
    if (!by[s.code]) { by[s.code] = { code: s.code, count: 0, marks: s.marks_per, mixed: false, intact: s.intact_blocks }; order.push(s.code); }
    if (s.marks_per !== by[s.code].marks) by[s.code].mixed = true;   // e.g. 1/2/3/5-mark MCQs in one section
    if (s.intact_blocks) {
      var cases = {};
      s.questions.forEach(function (q) { if (q.context_block_id != null) cases[q.context_block_id] = 1; });
      by[s.code].count += Object.keys(cases).length;
    } else {
      by[s.code].count += s.questions.length;
    }
  });
  return order.map(function (c) { return by[c]; });
}

function instructionsHtml() {
  var groups = sectionSummary();
  var totalUnits = groups.reduce(function (a, g) { return a + g.count; }, 0);
  var perSection = groups.map(function (g) {
    var tail = g.mixed ? " (marks as indicated against each)"
      : " of " + g.marks + " mark" + (g.marks === 1 ? "" : "s") + " each";
    return "Section " + g.code + " has " + g.count + (g.intact ? " case-based question" : " question") +
      (g.count === 1 ? "" : "s") + tail;
  }).join("; ");
  var lines = [
    "This question paper contains " + totalUnits + " questions in " + groups.length +
      " sections — " + groups.map(function (g) { return g.code; }).join(", ") + ".",
  ];
  if (data.multi_subject && (data.subjects || []).length) {
    lines.push("The paper is organised in subject parts — " + data.subjects.join(", ") +
      " — each beginning under its own heading; attempt every part.");
  }
  lines = lines.concat([
    "All questions are compulsory. Internal choice is not provided unless stated.",
    perSection + ".",
    "Marks for each question are indicated against it.",
    "Draw neat, labelled figures wherever required; use of calculators is not permitted.",
  ]);
  return '<div class="ginstr"><div class="gtitle">General Instructions:</div><ol>' +
    lines.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ol></div>";
}

// ---- shared document shell ----
const BASE_CSS = `${katexCss}
  @page { size: A4; margin: 10mm 9mm; }
  * { font-family: "Noto Serif", "Times New Roman", serif; }
  body { font-size: 11pt; color: #111; line-height: 1.4; }
  .head { text-align: center; border-bottom: 2px solid #000; padding-bottom: 6px; margin-bottom: 10px; }
  .head h1 { font-size: 16pt; margin: 0 0 2px; letter-spacing: .3px; }
  .head .sub { font-size: 10.5pt; color: #333; }
  .katex { font-size: 1.02em; }`;

const BRAND_CSS = `
  .brand { display: flex; align-items: center; gap: 38px; border-bottom: 2.5px solid #000; padding-bottom: 8px; margin-bottom: 10px; }
  .brand .blogo img { height: 19mm; display: block; }
  .brand .binfo { flex: 1; text-align: left; line-height: 1.22; }
  .brand .bname { font-family: Georgia, "Times New Roman", serif; font-weight: 700; font-size: 17pt; letter-spacing: .4px; margin: 0; line-height: 1.05; color: #000; }
  .brand .binfo .adr { font-size: 8.7pt; color: #2a2a2a; margin: 0; }
  .ptitle { text-align: center; font-size: 13pt; font-weight: 700; margin: 6px 0 8px; letter-spacing: .3px; }`;

function docHead(extraCss) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${BASE_CSS}${BRAND_CSS}${extraCss || ""}</style></head><body>` + brandHeader();
}

function brandHeader() {
  if (!school.school) return "";
  var logo = "";
  if (school.logo) {
    var lp = path.isAbsolute(school.logo) ? school.logo : path.join(schoolDir, school.logo);
    if (fs.existsSync(lp)) logo = '<img src="file://' + lp + '">';
  }
  var addr = (school.addressLines || [])
    .filter(function (l) { return !/reg\.?\s*code/i.test(l || ""); })
    .map(function (l) { return '<div class="adr">' + esc(l) + "</div>"; }).join("");
  return '<div class="brand">' + (logo ? '<div class="blogo">' + logo + "</div>" : "") +
    '<div class="binfo"><div class="bname">' + esc((school.school || "").toUpperCase()) + "</div>" + addr + "</div></div>";
}
function subtitle(tag) {
  return [data.class_label ? "Class " + data.class_label : "", data.subject, tag].filter(Boolean).join(" · ");
}
function headBlock(tag) {
  return `<div class="ptitle">${esc(data.paper_title || "Question Paper")}</div>` +
    `<div style="text-align:center;font-size:10pt;color:#333;margin-bottom:8px;">${esc(subtitle(tag))}</div>`;
}

function paperHtml() {
  var homework = data.purpose === "homework";
  var dateStr = fmtDate(data.exam_date);
  var cells = [["Class", data.class_label ? esc(data.class_label) : "—"]];
  if (!data.multi_subject) cells.push(["Subject", esc(data.subject || "—")]);
  if (!homework) {
    cells.push(["Time Allowed", esc(data.exam_duration || "—")]);
    cells.push(["Maximum Marks", esc(data.max_marks)]);
  }
  if (homework) cells.push(["Date", dateStr ? esc(dateStr) : "____________"]);
  var metaRow = cells.map(function (c) { return '<td><span class="mk">' + c[0] + ':</span> ' + c[1] + "</td>"; }).join("");
  var twoCol = data.two_column === true;

  // Page footer: school name · date · "Page x of y" — in the bottom margin box.
  var footFont = 'font-size: 8pt; color: #333; font-family: "Noto Serif", "Times New Roman", serif;';
  var pageExtras = `
    @page {
      @bottom-left { content: ${JSON.stringify((school.school || "").toUpperCase())}; ${footFont} }
      @bottom-center { content: ${JSON.stringify(dateStr)}; ${footFont} }
      @bottom-right { content: "Page " counter(page) " of " counter(pages); ${footFont} }
      ${data.watermark && logoAbs
        ? `background-image: linear-gradient(rgba(255,255,255,0.955), rgba(255,255,255,0.955)), url("file://${logoAbs}");
           background-repeat: no-repeat; background-position: center, center;
           background-size: 210mm 297mm, 95mm;`
        : ""}
    }`;
  var css = pageExtras + `
    table.metabar { width: 100%; border-collapse: collapse; margin: 6px 0 10px; font-size: 10pt; border-top: 1.2px solid #000; border-bottom: 1.2px solid #000; }
    table.metabar td { padding: 5px 8px; text-align: center; } table.metabar .mk { color: #444; }
    table.metabar td:first-child { text-align: left; }
    table.metabar td:last-child { text-align: right; }
    .ginstr { padding: 2px 0 0; margin: 0 0 8px; font-size: 9.6pt; }
    .ginstr .gtitle { font-weight: 700; text-decoration: underline; margin-bottom: 3px; }
    .ginstr ol { margin: 0; padding-left: 18px; } .ginstr li { margin: 1px 0; }
    .flow { ${twoCol ? "column-count: 2; column-gap: 8mm; column-rule: 1.2px solid #000;" : ""} }
    h2.sec { font-size: 12.5pt; text-align: center; margin: 12px 0 2px; border-top: 1px solid #000; padding-top: 5px; ${twoCol ? "column-span: all;" : ""} }
    .secnote { text-align: center; font-size: 9.5pt; color: #444; font-style: italic; margin: 0 0 7px; ${twoCol ? "column-span: all;" : ""} }
    .q { margin: 0 0 9px; break-inside: avoid; } .qhead { display: flex; gap: 6px; } .qno { font-weight: 700; } .qbody { flex: 1; }
    .marks { float: right; color: #333; font-weight: 600; }
    .opts { margin-top: 3px; display: flex; flex-wrap: wrap; gap: 4px 22px; } .opt { min-width: 40%; }
    .qimg { display: block; max-width: 55mm; margin: 4px 0; }
    .case { background: #f4f4f4; border: 0.5px solid #999; padding: 6px 8px; margin: 6px 0; font-size: 10.3pt; break-inside: avoid; ${twoCol ? "column-span: all;" : ""} }
    h2.subjpart { font-size: 13.5pt; text-align: center; text-transform: uppercase; letter-spacing: .5px; margin: 12px 0 0; border-top: 2px solid #000; padding: 4px 0 0; ${twoCol ? "column-span: all;" : ""} }`;
  return docHead(css) +
    `<div class="ptitle">${esc(data.paper_title || "Question Paper")}</div>` +
    `<table class="metabar"><tr>${metaRow}</tr></table>` + instructionsHtml() +
    `<div class="flow">${bodyWithSubjects()}</div></body></html>`;
}

// Emit a subject "Part" heading before each subject's first section (multi-subject papers).
function bodyWithSubjects() {
  var html = "", cur = null;
  data.sections.forEach(function (sec) {
    if (data.multi_subject && sec.subject && sec.subject !== cur) {
      cur = sec.subject;
      html += '<h2 class="subjpart">' + esc(cur) + "</h2>";
    }
    html += sectionHtml(sec);
  });
  return html;
}

function eachQuestion(fn) {
  data.sections.forEach(function (sec) { sec.questions.forEach(function (q) { fn(q, sec); }); });
}

function answerOf(q) {
  return (q.options && q.options.length)
    ? "(" + esc(q.correct_answer_display || q.correct_answer || "?") + ")"
    : renderLatex(q.correct_answer_latex || q.correct_answer || "—");
}

// A subject heading emitted (once per subject) inside answer/solution lists.
function subjMark(sec, state, cls) {
  if (!data.multi_subject || !sec.subject || sec.subject === state.cur) return "";
  state.cur = sec.subject;
  return '<div class="' + cls + '">' + esc(sec.subject) + "</div>";
}

function answersHtml() {
  var items = [], st = { cur: null }, onlyObjective = true;
  eachQuestion(function (q, sec) {
    if (q.type !== "mcq" && q.type !== "assertion_reason") onlyObjective = false;
    items.push(subjMark(sec, st, "asub") + '<div class="ai"><b>' + q.display_number + ".</b> " + answerOf(q) + "</div>");
  });
  // Objective-only keys are short "(a)"-style answers — 4 columns fit; papers
  // with written-answer types carry longer answers, so give them 3 columns.
  var cols = onlyObjective ? 4 : 3;
  var css = ".wrap{column-count:" + cols + ";column-gap:6mm;} .ai{break-inside:avoid;margin:3px 0;font-size:11pt;}" +
    " .asub{column-span:all;break-inside:avoid;font-weight:700;text-transform:uppercase;font-size:11pt;margin:8px 0 3px;border-bottom:1px solid #000;}";
  return docHead(css) + headBlock("Answer Key") + '<div class="wrap">' + items.join("") + "</div></body></html>";
}

function solutionsHtml() {
  var html = "", st = { cur: null };
  eachQuestion(function (q, sec) {
    html += subjMark(sec, st, "ssub");
    var sol = q.detailed_solution || q.explanation_latex || q.explanation || "";
    html += '<div class="sol"><div class="sq"><b>' + q.display_number + ".</b> " +
      renderLatex(q.question_latex || q.question_text || "") + "</div>" +
      '<div class="sa"><b>Answer:</b> ' + answerOf(q) + "</div>" +
      (sol ? '<div class="se">' + renderLatex(sol) + "</div>" : "") + "</div>";
  });
  var css = ".sol{margin:0 0 11px;break-inside:avoid;} .sq{margin-bottom:2px;} .sa{color:#065; font-size:10pt;} .se{margin-top:2px;font-size:10.3pt;color:#222;}" +
    " .ssub{font-weight:700;text-transform:uppercase;font-size:12pt;margin:10px 0 5px;border-bottom:1px solid #000;}";
  return docHead(css) + headBlock("Solutions & Explanations") + html + "</body></html>";
}

function metadataHtml() {
  var COLS = [["#", "n"]];
  if (data.multi_subject) COLS.push(["Subject", "subject"]);
  COLS = COLS.concat([["Chapter", "chapter"], ["Type", "type"], ["Marks", "marks"],
    ["Difficulty", "difficulty"], ["Topic", "topic"], ["Cognitive", "cognitive_level"],
    ["Page", "source_page"], ["PYQ", "pyq"]]);
  var head = COLS.map(function (c) { return "<th>" + c[0] + "</th>"; }).join("");
  var rows = "";
  eachQuestion(function (q, sec) {
    var pyq = q.is_pyq ? [q.pyq_exam, q.pyq_year].filter(Boolean).join(" ") : "";
    var val = {
      n: q.display_number, subject: sec.subject || "", chapter: q._chapter_name || "", type: q.type || "",
      marks: q.marks != null ? q.marks : (q.section_marks != null ? q.section_marks : ""),
      difficulty: q.difficulty || "", topic: q.topic || "", cognitive_level: q.cognitive_level || "",
      source_page: q.source_page != null ? q.source_page : "", pyq: pyq,
    };
    rows += "<tr>" + COLS.map(function (c) { return "<td>" + esc(val[c[1]]) + "</td>"; }).join("") + "</tr>";
  });
  var css = "@page{size:A4 landscape;} table{width:100%;border-collapse:collapse;font-size:9pt;} " +
    "th,td{border:0.5px solid #bbb;padding:3px 5px;text-align:left;vertical-align:top;} th{background:#eee;} td:first-child{text-align:right;}";
  return docHead(css) + headBlock("Question Metadata Report") +
    "<table><thead><tr>" + head + "</tr></thead><tbody>" + rows + "</tbody></table></body></html>";
}

const MODE = arg("mode", "paper");
const BUILDERS = { paper: paperHtml, answers: answersHtml, solutions: solutionsHtml, metadata: metadataHtml };
fs.writeFileSync(outPath, (BUILDERS[MODE] || paperHtml)());
console.log("wrote " + outPath + " (" + MODE + ")");
