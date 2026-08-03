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

// Escape, but keep the source's inline emphasis tags (<b>, <i>, <u>, <sup>,
// <sub>, <br>) — the question text uses them for emphasis (e.g. "<b>not</b>").
function escText(s) {
  return esc(s).replace(/&lt;(\/?(?:b|i|u|sup|sub|br)\s*\/?)&gt;/gi, "<$1>");
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

const meta = [
  data.class_label ? `Class ${esc(data.class_label)}` : "",
  esc(data.subject || ""),
  `Time: ${esc(data.exam_duration || "")}`,
  `Max Marks: ${esc(data.max_marks)}`,
].filter(Boolean).join(" &nbsp;·&nbsp; ");

const body = data.sections.map(sectionHtml).join("");

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
  ${katexCss}
  @page { size: A4; margin: 16mm 14mm; }
  * { font-family: "Noto Serif", "Times New Roman", serif; }
  body { font-size: 11pt; color: #111; line-height: 1.4; }
  h1.title { text-align: center; font-size: 15pt; margin: 0 0 4px; }
  .meta { text-align: center; font-size: 10pt; color: #333; border-bottom: 1.5px solid #000;
          padding-bottom: 6px; margin-bottom: 8px; }
  h2.sec { font-size: 12pt; text-align: center; margin: 14px 0 2px; border-top: 1px solid #999; padding-top: 6px; }
  .secnote { text-align: center; font-size: 9.5pt; color: #444; font-style: italic; margin: 0 0 8px; }
  .q { margin: 0 0 9px; }
  .qhead { display: flex; gap: 6px; }
  .qno { font-weight: 700; }
  .qbody { flex: 1; }
  .marks { float: right; color: #333; font-weight: 600; }
  .opts { margin-top: 3px; display: flex; flex-wrap: wrap; gap: 4px 22px; }
  .opt { min-width: 40%; }
  .qimg { display: block; max-width: 60mm; margin: 4px 0; }
  .case { background: #f4f4f4; border: 0.5px solid #bbb; padding: 6px 8px; margin: 6px 0; font-size: 10.5pt; }
  .katex { font-size: 1.02em; }
</style></head><body>
  <h1 class="title">${esc(data.paper_title || "Question Paper")}</h1>
  <div class="meta">${meta}</div>
  ${body}
</body></html>`;

fs.writeFileSync(outPath, html);
console.log("wrote " + outPath);
