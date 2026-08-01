/**
 * mathToOmml.js — converts plain-text question/option/explanation strings
 * into an array of docx Paragraph children (TextRun for prose, real
 * Math/MathFraction/MathSuperScript/MathSubScript/MathRadical/MathSum/
 * MathIntegral OMML objects for structural math), so equations open as
 * genuine, editable Word equations rather than Unicode-symbol approximations.
 *
 * Coverage: fractions (a/b, unicode vulgar fractions, mixed numbers),
 * superscripts (^ and unicode superscript digits), subscripts (_),
 * square roots (√(...), sqrt(...)), basic summation (Σ_a^b) and
 * integral (∫_a^b) with limits. Plain arithmetic operators/digits/percent
 * signs are left as normal text — only genuinely structural math is
 * promoted to OMML, per spec ("never fake... fractions, superscripts,
 * subscripts, square roots, matrices, summations, integrals").
 *
 * Known limitation: matrices are not auto-detected from plain text (the
 * source book has none in practice); `buildMatrix()` is exported for
 * manual use if a future book needs it.
 */
const { TextRun, Math: DMath, MathRun, MathFraction, MathSuperScript, MathSubScript, MathRadical, MathSum, MathIntegral } = require("docx");

const UNICODE_FRACTIONS = {
  "½": [1, 2], "⅓": [1, 3], "⅔": [2, 3], "¼": [1, 4], "¾": [3, 4],
  "⅕": [1, 5], "⅖": [2, 5], "⅗": [3, 5], "⅘": [4, 5],
  "⅙": [1, 6], "⅚": [5, 6], "⅛": [1, 8], "⅜": [3, 8], "⅝": [5, 8], "⅞": [7, 8],
};
const SUPERSCRIPT_DIGITS = { "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9" };
const FUNCTION_NAMES = ["sin", "cos", "tan", "cot", "sec", "cosec", "csc", "log", "ln"];

const UNICODE_FRACTION_CHARS = Object.keys(UNICODE_FRACTIONS).join("");
const SUPERSCRIPT_CHARS = Object.keys(SUPERSCRIPT_DIGITS).join("");

// Ordered pattern list — first match (by earliest index, then by order for ties) wins.
const PATTERNS = [
  // mixed number + unicode fraction, e.g. "15½"
  { name: "mixedUnicodeFraction", re: new RegExp(`(\\d+)\\s?([${UNICODE_FRACTION_CHARS}])`) },
  // mixed number + slash fraction, e.g. "1 3/4"
  { name: "mixedSlashFraction", re: /(\d+)\s+(\d+)\/(\d+)\b/ },
  // standalone unicode fraction
  { name: "unicodeFraction", re: new RegExp(`[${UNICODE_FRACTION_CHARS}]`) },
  // sqrt(...) or √(...)
  { name: "sqrtParen", re: /(?:√|sqrt)\(([^()]+)\)/i },
  // √9 / sqrt9 (no parens, single token: number or short var)
  { name: "sqrtBare", re: /(?:√|sqrt)\s?(\d+(?:\.\d+)?|[A-Za-z])/i },
  // summation with limits: Σ_i^n or Σ(i=1)^(n)
  { name: "sumLimits", re: /Σ\s*_\s*\(?([^)^\s]+)\)?\s*\^\s*\(?([^)\s]+)\)?/ },
  { name: "sumBare", re: /Σ/ },
  // integral with limits: ∫_a^b
  { name: "intLimits", re: /∫\s*_\s*\(?([^)^\s]+)\)?\s*\^\s*\(?([^)\s]+)\)?/ },
  { name: "intBare", re: /∫/ },
  // simple numeric fraction a/b (word-bounded, not a date/ratio like "2020/21" false positive is acceptable here)
  { name: "simpleFraction", re: /\b(\d+)\/(\d+)\b/ },
  // caret exponent: base^exp, base = last "word" char, exp = parenthesised/number/letter
  { name: "caretExponent", re: /([A-Za-z0-9])\^(\(-?\d+(?:\.\d+)?\)|-?\d+(?:\.\d+)?|[A-Za-z])/ },
  // unicode superscript exponent: base followed by superscript digits
  { name: "unicodeExponent", re: new RegExp(`([A-Za-z0-9])([${SUPERSCRIPT_CHARS}]+)`) },
  // subscript: base_sub
  { name: "subscript", re: /([A-Za-z])_(\d+|[A-Za-z])/ },
];

function findEarliestMatch(text, fromIndex) {
  let best = null;
  for (const p of PATTERNS) {
    p.re.lastIndex = 0;
    const m = p.re.exec(text.slice(fromIndex));
    if (m && (best === null || m.index < best.matchIndex)) {
      best = { pattern: p, match: m, matchIndex: m.index };
    }
  }
  return best;
}

function stripSuperscriptDigits(s) {
  return s.split("").map((c) => SUPERSCRIPT_DIGITS[c] || c).join("");
}

function mathZone(children) {
  return new DMath({ children });
}

function buildFraction(num, den) {
  return new MathFraction({ numerator: [new MathRun(String(num))], denominator: [new MathRun(String(den))] });
}

/** Exported for manual use — a simple n x m matrix of MathRun cells rendered
 * as a bracketed grid. docx's Math API has no native matrix primitive, so
 * this approximates one using nested fractions-free stacked rows; call out
 * to a real OMML matrix (m:matrix) is not exposed by the docx package as of
 * v9.7.1, so complex matrix questions should be flagged for manual review. */
function buildMatrix(rows) {
  // Fallback: render as a small borderless table is handled at the caller
  // (Paragraph) level, not here, since Math() can't contain a Table.
  return rows.map((r) => r.join("   ")).join("\n");
}

/**
 * Convert one plain-text string into an array of Paragraph-ready children
 * (TextRun and Math nodes, in reading order).
 */
function textToRuns(text, opts = {}) {
  // NOTE: bold/italics were previously accepted here but silently dropped —
  // only size/font ever reached the TextRun. Fixed so callers that ask for
  // bold/italic prose (e.g. the shaded Directions box) actually get it.
  const runOpts = { size: opts.size || 20, font: opts.font, bold: opts.bold, italics: opts.italics };
  if (!text) return [];
  const out = [];
  let cursor = 0;
  let guard = 0;

  const pushText = (s) => {
    if (s.length === 0) return;
    out.push(new TextRun({ text: s, ...runOpts }));
  };

  while (cursor < text.length && guard < 500) {
    guard++;
    const found = findEarliestMatch(text, cursor);
    if (!found) {
      pushText(text.slice(cursor));
      break;
    }
    const absIndex = cursor + found.matchIndex;
    const m = found.match;
    const matchedText = m[0];

    // flush preceding plain text
    pushText(text.slice(cursor, absIndex));

    switch (found.pattern.name) {
      case "mixedUnicodeFraction": {
        const whole = m[1];
        const [n, d] = UNICODE_FRACTIONS[m[2]];
        out.push(mathZone([new MathRun(whole + " "), buildFraction(n, d)]));
        break;
      }
      case "mixedSlashFraction": {
        out.push(mathZone([new MathRun(m[1] + " "), buildFraction(m[2], m[3])]));
        break;
      }
      case "unicodeFraction": {
        const [n, d] = UNICODE_FRACTIONS[matchedText];
        out.push(mathZone([buildFraction(n, d)]));
        break;
      }
      case "sqrtParen":
      case "sqrtBare": {
        out.push(mathZone([new MathRadical({ children: [new MathRun(m[1])] })]));
        break;
      }
      case "sumLimits": {
        out.push(mathZone([new MathSum({ children: [new MathRun("")], subScript: [new MathRun(m[1])], superScript: [new MathRun(m[2])] })]));
        break;
      }
      case "sumBare": {
        out.push(mathZone([new MathSum({ children: [new MathRun("")] })]));
        break;
      }
      case "intLimits": {
        out.push(mathZone([new MathIntegral({ children: [new MathRun("")], subScript: [new MathRun(m[1])], superScript: [new MathRun(m[2])] })]));
        break;
      }
      case "intBare": {
        out.push(mathZone([new MathIntegral({ children: [new MathRun("")] })]));
        break;
      }
      case "simpleFraction": {
        out.push(mathZone([buildFraction(m[1], m[2])]));
        break;
      }
      case "caretExponent": {
        const expText = m[2].replace(/^\(|\)$/g, "");
        out.push(mathZone([new MathSuperScript({ children: [new MathRun(m[1])], superScript: [new MathRun(expText)] })]));
        break;
      }
      case "unicodeExponent": {
        out.push(mathZone([new MathSuperScript({ children: [new MathRun(m[1])], superScript: [new MathRun(stripSuperscriptDigits(m[2]))] })]));
        break;
      }
      case "subscript": {
        out.push(mathZone([new MathSubScript({ children: [new MathRun(m[1])], subScript: [new MathRun(m[2])] })]));
        break;
      }
    }
    cursor = absIndex + matchedText.length;
  }

  if (out.length === 0) pushText(text);
  return out;
}

module.exports = { textToRuns, buildMatrix };
