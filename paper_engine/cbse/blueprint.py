"""
blueprint.py — the CBSE paper blueprint: which sections a paper has, what each
draws from, and how many questions/marks. This is the "board pattern" — very
different from the competitive selector's chapters x types x counts model.

A blueprint section:
  code         section letter shown on the paper ("A".."E")
  title        heading ("Section A")
  instruction  the line under the heading
  draw_types   DB question `type`s this section pulls from
  marks_per    marks per question in THIS section (standardized; the DB's own
               per-question marks vary, so the paper fixes them per section)
  count        how many questions (for case_based: how many CASE BLOCKS)
  intact_blocks  True => pick whole context_blocks (case studies) and keep all
                 their sub-questions together (like passages)

The default is the standard CBSE Class-VIII 80-mark pattern. The frontend/config
can override counts, marks, chapters and difficulty.
"""

# Standard CBSE (2023-onward) pattern, ~80 marks.
DEFAULT_SECTIONS = [
    {"code": "A", "title": "Section A", "instruction": "Multiple Choice Questions — 1 mark each.",
     "draw_types": ["mcq"], "marks_per": 1, "count": 16, "intact_blocks": False},
    {"code": "A-AR", "title": "", "instruction": "Assertion–Reason — 1 mark each.",
     "draw_types": ["assertion_reason"], "marks_per": 1, "count": 4, "intact_blocks": False},
    {"code": "B", "title": "Section B", "instruction": "Very Short Answer — 2 marks each.",
     "draw_types": ["very_short_answer"], "marks_per": 2, "count": 5, "intact_blocks": False},
    {"code": "C", "title": "Section C", "instruction": "Short Answer — 3 marks each.",
     "draw_types": ["short_answer"], "marks_per": 3, "count": 6, "intact_blocks": False},
    {"code": "D", "title": "Section D", "instruction": "Long Answer — 5 marks each.",
     "draw_types": ["long_answer"], "marks_per": 5, "count": 4, "intact_blocks": False},
    {"code": "E", "title": "Section E", "instruction": "Case-Based Questions — 4 marks each.",
     "draw_types": ["case_based"], "marks_per": 4, "count": 3, "intact_blocks": True},
]


def default_blueprint():
    """A fresh copy of the default section list."""
    return [dict(s) for s in DEFAULT_SECTIONS]


def resolve_sections(cfg):
    """
    Merge the config's per-section overrides onto the default blueprint.
    cfg['sections'] (optional) is {code: {count?, marks_per?}} — anything omitted
    keeps the default. cfg may also drop a section by setting its count to 0.
    """
    overrides = cfg.get("sections") or {}
    out = []
    for sec in default_blueprint():
        ov = overrides.get(sec["code"]) or {}
        if "count" in ov:
            sec["count"] = int(ov["count"])
        if "marks_per" in ov:
            sec["marks_per"] = float(ov["marks_per"])
        if sec["count"] > 0:
            out.append(sec)
    return out
