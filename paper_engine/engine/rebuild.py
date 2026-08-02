"""
rebuild.py — regenerate a paper with the EXACT same questions, but freshly
re-fetched from the DB (and images re-read at docx-build time).

Use case: after a paper is generated, a question's text/options/figure/answer is
corrected in the question bank. Regenerating must reproduce the *same* questions
in the *same* order with the *same* numbering — only their content refreshed. So
we DON'T re-select; we take the question ids (and their placement) straight out
of the paper's saved paper_content.json and re-hydrate each id from the DB.
"""
from . import db, fetch, output


def rebuild_from_content(qcon, old_content, image_base):
    warnings = []
    sections_out = []
    missing = []

    for sec in old_content.get("sections", []):
        section_name = sec.get("section_name")
        questions = []
        for oldq in sec.get("questions", []):
            qid = oldq.get("id")
            q = fetch.fetch_full_question(qcon, qid)  # FRESH content from the DB
            if q is None:
                missing.append(qid)
                continue
            # preserve the original placement/number exactly
            q["display_number"] = oldq.get("display_number")
            row = db.one(
                qcon,
                "SELECT c.name AS nm, c.chapter_number AS cn "
                "FROM questions qq JOIN chapters c ON qq.chapter_id = c.id WHERE qq.id = ?",
                (qid,),
            )
            q["_chapter_name"] = row["nm"] if row else None
            q["_chapter_number"] = row["cn"] if row else None
            questions.append(q)
        sections_out.append({"section_name": section_name, "questions": questions})

    if missing:
        warnings.append(
            f"{len(missing)} question(s) no longer exist in the DB and were dropped: {missing}"
        )

    cfg = {
        "paper_title": old_content.get("paper_title", "Question Paper"),
        "output_name": old_content.get("output_name", "paper"),
        "language": old_content.get("language"),
        "exam_duration": old_content.get("exam_duration", "2 Hours"),
        "exam_date": old_content.get("exam_date"),
        "numbering": "continuous",  # unused: renumber=False keeps original numbers
    }
    return output.build_output(cfg, sections_out, warnings, image_base, renumber=False)
