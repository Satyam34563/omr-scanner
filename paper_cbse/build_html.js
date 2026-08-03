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
  const marks = q.section_marks != null ? `<span class="marks">[${q.section_marks}]</span>` : "";
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
    if (!by[s.code]) { by[s.code] = { code: s.code, count: 0, marks: s.marks_per, intact: s.intact_blocks }; order.push(s.code); }
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
    return "Section " + g.code + " has " + g.count + (g.intact ? " case-based question" : " question") +
      (g.count === 1 ? "" : "s") + " of " + g.marks + " mark" + (g.marks === 1 ? "" : "s") + " each";
  }).join("; ");
  var lines = [
    "This question paper contains " + totalUnits + " questions in " + groups.length +
      " sections — " + groups.map(function (g) { return g.code; }).join(", ") + ".",
    "All questions are compulsory. Internal choice is not provided unless stated.",
    perSection + ".",
    "Marks for each question are indicated against it.",
    "Draw neat, labelled figures wherever required; use of calculators is not permitted.",
  ];
  return '<div class="ginstr"><div class="gtitle">General Instructions:</div><ol>' +
    lines.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ol></div>";
}

// ---- shared document shell ----
const BASE_CSS = `${katexCss}
  @page { size: A4; margin: 15mm 13mm; }
  * { font-family: "Noto Serif", "Times New Roman", serif; }
  body { font-size: 11pt; color: #111; line-height: 1.4; }
  .head { text-align: center; border-bottom: 2px solid #000; padding-bottom: 6px; margin-bottom: 10px; }
  .head h1 { font-size: 16pt; margin: 0 0 2px; letter-spacing: .3px; }
  .head .sub { font-size: 10.5pt; color: #333; }
  .katex { font-size: 1.02em; }`;

function docHead(extraCss) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${BASE_CSS}${extraCss || ""}</style></head><body>`;
}
function subtitle(tag) {
  return [data.class_label ? "Class " + data.class_label : "", data.subject, tag].filter(Boolean).join(" · ");
}
function headBlock(tag) {
  var t = data.paper_title || "Question Paper";
  return `<div class="head"><h1>${esc(t)}</h1><div class="sub">${esc(subtitle(tag))}</div></div>`;
}

function paperHtml() {
  var metaRow = [
    ["Class", data.class_label ? esc(data.class_label) : "—"],
    ["Subject", esc(data.subject || "—")],
    ["Time Allowed", esc(data.exam_duration || "—")],
    ["Maximum Marks", esc(data.max_marks)],
  ].map(function (c) { return '<td><span class="mk">' + c[0] + ':</span> ' + c[1] + "</td>"; }).join("");
  var twoCol = data.two_column === true;
  var css = `
    table.metabar { width: 100%; border-collapse: collapse; margin: 6px 0 10px; font-size: 10pt; }
    table.metabar td { border: 0.75px solid #000; padding: 4px 8px; } table.metabar .mk { color: #444; }
    .ginstr { border: 0.75px solid #000; padding: 6px 10px; margin: 0 0 12px; font-size: 9.6pt; }
    .ginstr .gtitle { font-weight: 700; text-decoration: underline; margin-bottom: 3px; }
    .ginstr ol { margin: 0; padding-left: 18px; } .ginstr li { margin: 1px 0; }
    .flow { ${twoCol ? "column-count: 2; column-gap: 8mm; column-rule: 0.5px solid #ccc;" : ""} }
    h2.sec { font-size: 12.5pt; text-align: center; margin: 12px 0 2px; border-top: 1px solid #000; padding-top: 5px; ${twoCol ? "column-span: all;" : ""} }
    .secnote { text-align: center; font-size: 9.5pt; color: #444; font-style: italic; margin: 0 0 7px; ${twoCol ? "column-span: all;" : ""} }
    .q { margin: 0 0 9px; break-inside: avoid; } .qhead { display: flex; gap: 6px; } .qno { font-weight: 700; } .qbody { flex: 1; }
    .marks { float: right; color: #333; font-weight: 600; }
    .opts { margin-top: 3px; display: flex; flex-wrap: wrap; gap: 4px 22px; } .opt { min-width: 40%; }
    .qimg { display: block; max-width: 55mm; margin: 4px 0; }
    .case { background: #f4f4f4; border: 0.5px solid #999; padding: 6px 8px; margin: 6px 0; font-size: 10.3pt; break-inside: avoid; ${twoCol ? "column-span: all;" : ""} }`;
  return docHead(css) +
    `<div class="head"><h1>${esc(data.paper_title || "Question Paper")}</h1>${data.book_title ? `<div class="sub">${esc(data.book_title)}</div>` : ""}</div>` +
    `<table class="metabar"><tr>${metaRow}</tr></table>` + instructionsHtml() +
    `<div class="flow">${data.sections.map(sectionHtml).join("")}</div></body></html>`;
}

function eachQuestion(fn) {
  data.sections.forEach(function (sec) { sec.questions.forEach(function (q) { fn(q, sec); }); });
}

function answerOf(q) {
  return (q.options && q.options.length)
    ? "(" + esc(q.correct_answer_display || q.correct_answer || "?") + ")"
    : renderLatex(q.correct_answer_latex || q.correct_answer || "—");
}

function answersHtml() {
  var items = [];
  eachQuestion(function (q) { items.push('<div class="ai"><b>' + q.display_number + ".</b> " + answerOf(q) + "</div>"); });
  var css = ".wrap{column-count:4;column-gap:6mm;} .ai{break-inside:avoid;margin:3px 0;font-size:11pt;}";
  return docHead(css) + headBlock("Answer Key") + '<div class="wrap">' + items.join("") + "</div></body></html>";
}

function solutionsHtml() {
  var html = "";
  eachQuestion(function (q) {
    var sol = q.detailed_solution || q.explanation_latex || q.explanation || "";
    html += '<div class="sol"><div class="sq"><b>' + q.display_number + ".</b> " +
      renderLatex(q.question_latex || q.question_text || "") + "</div>" +
      '<div class="sa"><b>Answer:</b> ' + answerOf(q) + "</div>" +
      (sol ? '<div class="se">' + renderLatex(sol) + "</div>" : "") + "</div>";
  });
  var css = ".sol{margin:0 0 11px;break-inside:avoid;} .sq{margin-bottom:2px;} .sa{color:#065; font-size:10pt;} .se{margin-top:2px;font-size:10.3pt;color:#222;}";
  return docHead(css) + headBlock("Solutions & Explanations") + html + "</body></html>";
}

function metadataHtml() {
  var COLS = [["#", "n"], ["Chapter", "chapter"], ["Type", "type"], ["Marks", "marks"],
    ["Difficulty", "difficulty"], ["Topic", "topic"], ["Cognitive", "cognitive_level"],
    ["Page", "source_page"], ["PYQ", "pyq"]];
  var head = COLS.map(function (c) { return "<th>" + c[0] + "</th>"; }).join("");
  var rows = "";
  eachQuestion(function (q) {
    var pyq = q.is_pyq ? [q.pyq_exam, q.pyq_year].filter(Boolean).join(" ") : "";
    var val = {
      n: q.display_number, chapter: q._chapter_name || "", type: q.type || "",
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
