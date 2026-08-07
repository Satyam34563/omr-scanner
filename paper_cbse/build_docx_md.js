/**
 * build_docx_md.js — CBSE DOCX path, stage 1: cbse_content.json -> pandoc
 * markdown (LaTeX math left intact as $...$ / $$...$$). A pandoc pass then
 * turns it into a .docx with NATIVE Word equations (OMML):
 *
 *   node build_docx_md.js --content cbse_content.json --image-base DIR \
 *       --mode paper|answers|solutions --out paper.md
 *   pandoc paper.md -f markdown+tex_math_dollars -t docx -o paper.docx
 *
 * No print layout happens here — Word lays the document out when opened —
 * which is why this path is fast even on a small server. Two-column layout,
 * watermark and the page footer are PDF-only features.
 */
const fs = require("fs");
const path = require("path");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : def;
}

const contentPath = arg("content");
const imageBase = arg("image-base", "");
const outPath = arg("out");
const MODE = arg("mode", "paper");
if (!contentPath || !outPath) {
  console.error("usage: node build_docx_md.js --content x.json --image-base DIR --mode paper|answers|solutions --out out.md");
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(contentPath, "utf8"));

// School branding — same lookup chain as build_html.js.
const schoolCandidates = [
  arg("school-config", ""),
  path.join(imageBase, "school_config.json"),
  path.join(__dirname, "..", "paper_docx", "school_config.json"),
].filter(Boolean);
let school = {};
for (const cand of schoolCandidates) {
  try { school = JSON.parse(fs.readFileSync(cand, "utf8")); break; } catch (e) { /* next */ }
}

// ---- text helpers -----------------------------------------------------------
// Convert a *_latex field to pandoc markdown WITHOUT touching math spans:
// outside $...$ the source's <b>/<i> tags become markdown emphasis and other
// HTML is stripped (pandoc's docx writer drops raw HTML silently otherwise).
function mdText(s) {
  if (s == null) return "";
  const parts = String(s).split(/(\$\$[\s\S]+?\$\$|\$[^$]+\$)/g);
  return parts.map(function (p, i) {
    if (i % 2 === 1) return p;               // math span — leave for pandoc
    return p
      .replace(/<b>([\s\S]*?)<\/b>/gi, "**$1**")
      .replace(/<i>([\s\S]*?)<\/i>/gi, "*$1*")
      .replace(/<u>([\s\S]*?)<\/u>/gi, "$1")
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<[^>]+>/g, "")
      .replace(/\|/g, "\\|");                // keep meta/answer tables intact
  }).join("").trim();
}

function imgMd(rel, width) {
  if (!rel) return "";
  const abs = path.isAbsolute(rel) ? rel : path.join(imageBase, rel);
  if (!fs.existsSync(abs)) return "";
  return "![](" + abs + "){width=" + (width || "2.2in") + "}";
}

function questionImages(q) {
  let refs = q.question_images;
  if (typeof refs === "string") { try { refs = JSON.parse(refs); } catch (e) { refs = []; } }
  return (refs || []).map(function (r) { return imgMd(r); }).filter(Boolean).join("\n");
}

function explanationImages(q) {
  let refs = q.explanation_images;
  if (typeof refs === "string") { try { refs = JSON.parse(refs); } catch (e) { refs = []; } }
  return (refs || []).map(function (r) { return imgMd(r); }).filter(Boolean).join("\n");
}

function fmtDate(s) {
  if (!s) return "";
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return String(s);
  const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return parseInt(m[3], 10) + " " + MON[parseInt(m[2], 10) - 1] + " " + m[1];
}

function answerOf(q) {
  return (q.options && q.options.length)
    ? "(" + (q.correct_answer_display || q.correct_answer || "?") + ")"
    : mdText(q.correct_answer_latex || q.correct_answer || "—");
}

function eachQuestion(fn) {
  data.sections.forEach(function (sec) { sec.questions.forEach(function (q) { fn(q, sec); }); });
}

// ---- shared head ------------------------------------------------------------
function brandMd() {
  let out = "";
  if (school.logo) {
    const lp = path.isAbsolute(school.logo) ? school.logo
      : path.join(path.dirname(schoolCandidates.find(function (c) { try { fs.accessSync(c); return true; } catch (e) { return false; } }) || imageBase), school.logo);
    if (fs.existsSync(lp)) out += "![](" + lp + "){height=0.7in}\n\n";
  }
  if (school.school) out += "# " + school.school.toUpperCase() + "\n\n";
  const addr = (school.addressLines || []).filter(function (l) { return !/reg\.?\s*code/i.test(l || ""); });
  if (addr.length) out += addr.join(" · ") + "\n\n";
  out += "---\n\n";
  return out;
}

function titleMd(tag) {
  let out = "## " + (data.paper_title || "Question Paper") + (tag ? " — " + tag : "") + "\n\n";
  return out;
}

function metaMd() {
  const homework = data.purpose === "homework";
  const cells = [["Class", data.class_label || "—"]];
  if (!data.multi_subject) cells.push(["Subject", data.subject || "—"]);
  if (!homework) {
    cells.push(["Time Allowed", data.exam_duration || "—"]);
    cells.push(["Maximum Marks", String(data.max_marks)]);
  }
  if (homework) cells.push(["Date", fmtDate(data.exam_date) || "____________"]);
  const header = cells.map(function (c) { return c[0]; }).join(" | ");
  const rule = cells.map(function () { return "---"; }).join(" | ");
  const row = cells.map(function (c) { return c[1]; }).join(" | ");
  return "| " + header + " |\n| " + rule + " |\n| " + row + " |\n\n";
}

function sectionSummary() {
  const order = [], by = {};
  data.sections.forEach(function (s) {
    if (!by[s.code]) { by[s.code] = { code: s.code, count: 0, marks: s.marks_per, mixed: false, intact: s.intact_blocks }; order.push(s.code); }
    if (s.marks_per !== by[s.code].marks) by[s.code].mixed = true;
    if (s.intact_blocks) {
      const cases = {};
      s.questions.forEach(function (q) { if (q.context_block_id != null) cases[q.context_block_id] = 1; });
      by[s.code].count += Object.keys(cases).length;
    } else {
      by[s.code].count += s.questions.length;
    }
  });
  return order.map(function (c) { return by[c]; });
}

function instructionsMd() {
  const groups = sectionSummary();
  const totalUnits = groups.reduce(function (a, g) { return a + g.count; }, 0);
  const perSection = groups.map(function (g) {
    const tail = g.mixed ? " (marks as indicated against each)"
      : " of " + g.marks + " mark" + (g.marks === 1 ? "" : "s") + " each";
    return "Section " + g.code + " has " + g.count + (g.intact ? " case-based question" : " question") +
      (g.count === 1 ? "" : "s") + tail;
  }).join("; ");
  const lines = ["This question paper contains " + totalUnits + " questions in " + groups.length +
    " sections — " + groups.map(function (g) { return g.code; }).join(", ") + "."];
  if (data.multi_subject && (data.subjects || []).length) {
    lines.push("The paper is organised in subject parts — " + data.subjects.join(", ") +
      " — each beginning under its own heading; attempt every part.");
  }
  lines.push(
    "All questions are compulsory. Internal choice is not provided unless stated.",
    perSection + ".",
    "Marks for each question are indicated against it.",
    "Draw neat, labelled figures wherever required; use of calculators is not permitted."
  );
  return "**General Instructions:**\n\n" +
    lines.map(function (l, i) { return (i + 1) + ". " + l; }).join("\n") + "\n\n";
}

// ---- question rendering -----------------------------------------------------
function optionsMd(q) {
  if (!q.options || !q.options.length) return "";
  return q.options.map(function (o) {
    const img = o.image ? " " + imgMd(o.image, "1.4in") : "";
    return "**(" + o.label + ")** " + mdText(o.text_latex || o.text || "") + img;
  }).join("   ") + "\n\n";
}

function questionMd(q) {
  const marks = (data.show_question_marks !== false && q.section_marks != null)
    ? "   **[" + q.section_marks + "]**" : "";
  let out = "**" + q.display_number + ".** " + mdText(q.question_latex || q.question_text || "") + marks + "\n\n";
  const imgs = questionImages(q);
  if (imgs) out += imgs + "\n\n";
  out += optionsMd(q);
  return out;
}

function paperMd() {
  let out = brandMd() + titleMd("") + metaMd() + instructionsMd();
  let curSubject = null;
  data.sections.forEach(function (sec) {
    if (data.multi_subject && sec.subject && sec.subject !== curSubject) {
      curSubject = sec.subject;
      out += "# " + curSubject.toUpperCase() + "\n\n";
    }
    if (sec.title) out += "### " + sec.title + "\n\n";
    if (sec.instruction) out += "*" + sec.instruction + "*\n\n";
    if (sec.intact_blocks) {
      let curCb;
      sec.questions.forEach(function (q) {
        if (q.context_block_id !== curCb) {
          curCb = q.context_block_id;
          const cb = (data.context_blocks || {})[String(curCb)];
          if (cb) {
            out += "> " + mdText(cb.text_latex || cb.text || "").replace(/\n/g, "\n> ") + "\n";
            const ci = imgMd(cb.image);
            if (ci) out += ">\n> " + ci + "\n";
            out += "\n";
          }
        }
        out += questionMd(q);
      });
    } else {
      sec.questions.forEach(function (q) { out += questionMd(q); });
    }
  });
  return out;
}

function answersMd() {
  let out = brandMd() + titleMd("Answer Key");
  const cells = [];
  eachQuestion(function (q) { cells.push("**" + q.display_number + ".** " + answerOf(q)); });
  // 4-across table so the key stays compact
  const per = 4;
  out += "| " + Array(per).fill(" ").join(" | ") + " |\n";
  out += "| " + Array(per).fill("---").join(" | ") + " |\n";
  for (let i = 0; i < cells.length; i += per) {
    const row = cells.slice(i, i + per);
    while (row.length < per) row.push(" ");
    out += "| " + row.join(" | ") + " |\n";
  }
  return out + "\n";
}

function solutionsMd() {
  let out = brandMd() + titleMd("Solutions & Explanations");
  let curSubject = null;
  eachQuestion(function (q, sec) {
    if (data.multi_subject && sec.subject && sec.subject !== curSubject) {
      curSubject = sec.subject;
      out += "# " + curSubject.toUpperCase() + "\n\n";
    }
    out += "**" + q.display_number + ".** " + mdText(q.question_latex || q.question_text || "") + "\n\n";
    out += "**Answer:** " + answerOf(q) + "\n\n";
    const sol = q.detailed_solution || q.explanation_latex || q.explanation || "";
    if (sol) out += mdText(sol) + "\n\n";
    const solImgs = explanationImages(q);
    if (solImgs) out += solImgs + "\n\n";
  });
  return out;
}

const BUILDERS = { paper: paperMd, answers: answersMd, solutions: solutionsMd };
fs.writeFileSync(outPath, (BUILDERS[MODE] || paperMd)());
console.log("wrote " + outPath + " (" + MODE + ", markdown)");
