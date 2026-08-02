"""
output.py — assemble the final paper_content.json in the exact shape that the
existing build_docx.js consumes (mirrors the original select_questions.py output).

Responsibilities: assign display numbering, resolve image paths to absolute,
apply the Hindi Krutidev cleanup, dedupe context blocks, strip internal helper
keys, and package the top-level object.
"""
import os
import re

from .textfix import deep_fix_devanagari

# Inline image references embedded in text (question stem, explanation, context
# block) come in two source shapes; both are normalized to one canonical marker
# "{img:/abs/path}" that build_docx.js renders on its own line between the text:
#   {img:images/foo.png}   (question stems — analogy figures, etc.)
#   (images/foo.png)       (explanations / context blocks — "…figure (images/…)…")
_INLINE_BRACE = re.compile(r"\{img:\s*(images/[^{}]+?\.(?:png|jpe?g))\s*\}", re.I)
_INLINE_PAREN = re.compile(r"\(\s*(images/[^()]+?\.(?:png|jpe?g))\s*\)", re.I)


def _normalize_inline_images(text, image_base):
    if not text or not isinstance(text, str):
        return text
    repl = lambda m: "{img:" + os.path.join(image_base, m.group(1)) + "}"
    text = _INLINE_BRACE.sub(repl, text)
    text = _INLINE_PAREN.sub(repl, text)
    return text


def _assign_numbering(sections_out, numbering):
    counter = 1
    for sec in sections_out:
        if numbering == "per_section":
            counter = 1
        for q in sec["questions"]:
            q["display_number"] = counter
            counter += 1


def _resolve_images(sections_out, image_base):
    for sec in sections_out:
        for q in sec["questions"]:
            q["question_images"] = [os.path.join(image_base, p) for p in q["question_images"]]
            for opt in q["options"]:
                if opt.get("image"):
                    opt["image"] = os.path.join(image_base, opt["image"])


def _dedupe_context_blocks(all_qs):
    blocks = {}
    for q in all_qs:
        cb = q.get("_context_block")
        if cb:
            blocks[str(cb["id"])] = {
                "id": cb["id"],
                "type": cb["type"],
                "category": cb.get("category"),
                "text": cb["text"],
            }
    return blocks


def build_output(cfg, sections_out, warnings, image_base, renumber=True):
    # renumber=False keeps each question's existing display_number (used by the
    # regenerate/rebuild path, which must reproduce the original numbering).
    if renumber:
        _assign_numbering(sections_out, cfg["numbering"])
    _resolve_images(sections_out, image_base)

    for sec in sections_out:
        for q in sec["questions"]:
            deep_fix_devanagari(q)

    all_qs = [q for sec in sections_out for q in sec["questions"]]
    blocks = _dedupe_context_blocks(all_qs)

    # normalize inline image references in every text field -> {img:ABS} markers
    for q in all_qs:
        q["question_text"] = _normalize_inline_images(q.get("question_text"), image_base)
        q["explanation"] = _normalize_inline_images(q.get("explanation"), image_base)
        for opt in q.get("options", []):
            opt["text"] = _normalize_inline_images(opt.get("text"), image_base)
    for b in blocks.values():
        b["text"] = _normalize_inline_images(b.get("text"), image_base)

    # strip internal helper keys now that everything derived from them is done
    for q in all_qs:
        q["context_block_id"] = q["_context_block"]["id"] if q.get("_context_block") else None
        for k in ("_context_block", "_chapter_number", "_passage_order"):
            q.pop(k, None)

    total = sum(len(sec["questions"]) for sec in sections_out)

    return {
        "paper_title": cfg["paper_title"],
        "output_name": cfg["output_name"],
        "language": cfg["language"],
        "exam_duration": cfg["exam_duration"],
        "exam_date": cfg["exam_date"],
        "show_question_marks": cfg.get("show_question_marks", True),
        "total_questions": total,
        "sections": sections_out,
        "context_blocks": blocks,
        "warnings": warnings,
    }
