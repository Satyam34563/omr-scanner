"""
blueprint.py — the CBSE paper blueprint.

A blueprint is an ordered list of BUCKETS. Each bucket selects questions of a
given `type` + `marks` (so the different mark-schemes inside one type — e.g. the
1/2/3/5-mark MCQs — are handled explicitly), and its `count` is distributed
ACROSS chapters (equal split, or an explicit per-chapter map). Buckets are
grouped into printed sections by `code` ("A".."E").

  key       unique id used for config overrides
  code      printed section letter (buckets sharing a code print under one heading)
  title     section heading (blank => continues the previous section)
  instruction  the line under the heading
  types     DB question `type`s this bucket pulls from
  marks     marks per question (also the source-marks filter; None for case blocks)
  count     how many questions (for intact buckets: how many CASE BLOCKS)
  intact    True => whole context_blocks (case studies), sub-questions kept together
  chapters  optional {chapter_id: count} explicit split; None => equal split

The default is the standard CBSE Class-VIII pattern (marks match what the DB
actually holds, so paper marks are honest).
"""

DEFAULT_BUCKETS = [
    {"key": "A_MCQ", "code": "A", "title": "Section A", "instruction": "Multiple Choice Questions — 1 mark each.",
     "types": ["mcq"], "marks": 1, "count": 16, "intact": False},
    {"key": "A_AR", "code": "A", "title": "", "instruction": "Assertion–Reason — 1 mark each.",
     "types": ["assertion_reason"], "marks": 1, "count": 4, "intact": False},
    {"key": "B", "code": "B", "title": "Section B", "instruction": "Very Short Answer.",
     "types": ["very_short_answer"], "marks": 1, "count": 5, "intact": False},
    {"key": "C", "code": "C", "title": "Section C", "instruction": "Short Answer — 3 marks each.",
     "types": ["short_answer"], "marks": 3, "count": 6, "intact": False},
    {"key": "D", "code": "D", "title": "Section D", "instruction": "Long Answer — 5 marks each.",
     "types": ["long_answer"], "marks": 5, "count": 4, "intact": False},
    {"key": "E", "code": "E", "title": "Section E", "instruction": "Case-Based Questions — 4 marks each.",
     "types": ["case_based"], "marks": 4, "count": 3, "intact": True},
]


def default_blueprint():
    return [dict(b) for b in DEFAULT_BUCKETS]


def resolve_buckets(cfg):
    """
    Merge cfg['sections'] (a {key: {count?, marks?, chapters?}} map) onto the
    default buckets. A bucket with count 0 is dropped.
    """
    overrides = cfg.get("sections") or {}
    out = []
    for b in default_blueprint():
        ov = overrides.get(b["key"]) or {}
        if "count" in ov:
            b["count"] = int(ov["count"])
        if "marks" in ov and ov["marks"] is not None:
            b["marks"] = float(ov["marks"])
        if "chapters" in ov and ov["chapters"]:
            b["chapters"] = {int(k): int(v) for k, v in ov["chapters"].items()}
        if b["count"] > 0:
            out.append(b)
    return out
