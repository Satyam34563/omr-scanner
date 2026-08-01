"""
selector.py — orchestrates a full paper selection.

For each section: build its per-section filter spec, figure out per-chapter
counts (explicit map, or equal-split of the section total across eligible
chapters), then let the chosen mode pick ids from each chapter's candidate pool.
Returns the raw section structure + the flat list of chosen question ids (for
usage recording) + warnings.
"""
import dataclasses
import random

from . import db, metadata, fetch, modes, passages, units
from .alloc import equal_allocate
from .filters import FilterSpec


def _section_spec(cfg, sec) -> FilterSpec:
    f = sec["filters"]
    return FilterSpec(
        language=cfg["language"],
        section_ids=[sec["section_id"]],
        types=f["types"],
        pyq_only=f["pyq_only"],
        pyq_years=f["pyq_years"],
        pyq_exams=f["pyq_exams"],
        exclude_ids=cfg["exclude_ids"],
    )


def _blank_section(sid):
    return {
        "section_id": sid,
        "total_questions": None,
        "filters": {"types": [], "pyq_only": False, "pyq_years": [], "pyq_exams": []},
        "selection_mode": None,
        "chapters": None,
    }


def select_paper(qcon, usage_map, cfg):
    rng = random.Random(cfg["random_seed"])  # None => nondeterministic
    strategy = cfg["shortfall_strategy"]
    warnings = []
    sections_out = []
    chosen_ids = []

    # No sections configured => include ALL sections of the language (blank), so
    # the paper total gets split equally across every section and then every
    # chapter. Configured sections restrict/override instead.
    sections_cfg = cfg["sections"]
    if not sections_cfg:
        secs = metadata.sections(qcon, FilterSpec(language=cfg["language"]))
        sections_cfg = [_blank_section(s["id"]) for s in secs]
        if not sections_cfg:
            warnings.append(f"no sections found for language '{cfg['language']}'.")

    # ---- resolve each section's target count ----
    # A section is driven by (a) its explicit chapters map, (b) its own
    # total_questions, or (c) a share of the paper-level total. Sections in (c)
    # split whatever the paper total has left after (a)+(b) are accounted for,
    # proportioned by each one's eligible pool.
    resolved_total = {}
    allocated = 0
    share_idx = []
    for i, sec in enumerate(sections_cfg):
        if sec["chapters"]:
            resolved_total[i] = None
            allocated += sum(sec["chapters"].values())
        elif sec["total_questions"] is not None:
            resolved_total[i] = sec["total_questions"]
            allocated += sec["total_questions"]
        else:
            share_idx.append(i)
    if share_idx:
        remaining = max(0, (cfg.get("total_questions") or 0) - allocated)
        caps = {i: metadata.pool_size(qcon, _section_spec(cfg, sections_cfg[i])) for i in share_idx}
        shares, w = equal_allocate(remaining, caps, rng, strategy)
        warnings.extend(w)
        for i in share_idx:
            resolved_total[i] = shares.get(i, 0)

    for idx, sec in enumerate(sections_cfg):
        sid = sec["section_id"]
        srow = db.one(qcon, "SELECT id, name FROM sections WHERE id=?", (sid,))
        if not srow:
            warnings.append(f"section_id {sid} not found in DB — skipped.")
            continue
        section_name = srow["name"]
        mode = sec["selection_mode"] or cfg["selection_mode"]

        spec = _section_spec(cfg, sec)

        # ---- passage-aware path for language / reading-comprehension sections ----
        # When every eligible question belongs to a passage, select whole
        # passages (with the trim-the-last-one rule) instead of splitting them
        # across chapters. See passages.py.
        if passages.is_passage_section(qcon, spec):
            if resolved_total.get(idx) is not None:
                target = resolved_total[idx]
            elif sec["chapters"]:
                target = sum(sec["chapters"].values())
            else:
                target = 0
            pq, w = passages.select_passage_section(qcon, spec, target, mode, usage_map, rng)
            warnings.extend(f"[{section_name}] {msg}" for msg in w)
            pq.sort(key=lambda q: (q.get("_passage_order") or 0, q.get("question_number") or 0))
            for q in pq:
                chosen_ids.append(q["id"])
            sections_out.append({
                "section_name": section_name,
                "questions": pq,
                "mode": mode,
                "take_counts": {"passages_used": len({q.get("_passage_id") for q in pq})},
            })
            continue

        chapters = metadata.chapters(qcon, spec)  # id,name,chapter_number,section_id,count
        avail = {c["id"]: c["count"] for c in chapters}
        cname = {c["id"]: c["name"] for c in chapters}
        cnum = {c["id"]: c["chapter_number"] for c in chapters}

        # ---- resolve per-chapter target counts ----
        if sec["chapters"]:  # explicit map cid->count
            take_counts = {}
            for cid, want in sec["chapters"].items():
                if cid not in avail:
                    warnings.append(
                        f"[{section_name}] chapter_id {cid} has no eligible questions "
                        f"under this section's filters — skipped."
                    )
                    continue
                got = min(want, avail[cid])
                if got < want:
                    warnings.append(
                        f"[{section_name}] chapter_id {cid} requested {want} but only {got} eligible."
                    )
                if got > 0:
                    take_counts[cid] = got
        else:
            target = resolved_total.get(idx) or 0
            take_counts, w = equal_allocate(target, avail, rng, strategy)
            warnings.extend(f"[{section_name}] {msg}" for msg in w)

        # ---- pick ids per chapter, then hydrate ----
        sec_questions = []
        for cid, n in take_counts.items():
            spec_ch = dataclasses.replace(spec, chapter_ids=[cid])
            cands = fetch.candidate_rows(qcon, spec_ch)
            ids = units.pick(mode, cands, n, usage_map, rng, strategy)
            for qid in ids:
                q = fetch.fetch_full_question(qcon, qid)
                q["_chapter_name"] = cname.get(cid)
                q["_chapter_number"] = cnum.get(cid)
                sec_questions.append(q)
                chosen_ids.append(qid)

        # Order questions by (chapter, question_number), but keep the sub-
        # questions of an intact block (passage / question_block) CONTIGUOUS,
        # anchored at the block's first selected question, so the renderer can
        # print the shared block once directly above its group.
        _anchor = {}
        for q in sec_questions:
            cb = q.get("_context_block")
            if cb and cb.get("type") in units.INTACT_TYPES:
                qn = q.get("question_number") or 0
                _anchor[cb["id"]] = min(_anchor.get(cb["id"], qn), qn)

        def _order(q):
            cn = q.get("_chapter_number") or 999
            qn = q.get("question_number") or 0
            cb = q.get("_context_block")
            if cb and cb.get("type") in units.INTACT_TYPES:
                return (cn, _anchor[cb["id"]], cb["id"], qn, q["id"])
            return (cn, qn, 0, qn, q["id"])

        sec_questions.sort(key=_order)
        sections_out.append({
            "section_name": section_name,
            "questions": sec_questions,
            "mode": mode,
            "take_counts": {str(k): v for k, v in take_counts.items()},
        })

    return sections_out, chosen_ids, warnings
