"""
cli/cbse_metadata.py — JSON metadata for the CBSE form (classes, chapters,
difficulties, paper_tags, buckets). Read-only against questionsitoviii.db.

    python3 -m cli.cbse_metadata --db /path/questionsitoviii.db --query classes
    python3 -m cli.cbse_metadata --db ... --query chapters --class-number 8
"""
import argparse
import json
import sys

from engine import db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--query", required=True,
                     choices=["classes", "subjects", "chapters", "difficulties", "paper_tags", "buckets"])
    ap.add_argument("--class-number", type=int)
    ap.add_argument("--subject")
    ap.add_argument("--paper-tags", help="JSON array of tags — 'chapters' restricts its availability counts to these (optional)")
    args = ap.parse_args()

    paper_tags_filter = []
    if args.paper_tags:
        try:
            paper_tags_filter = [str(t) for t in (json.loads(args.paper_tags) or []) if t]
        except (TypeError, ValueError):
            paper_tags_filter = []

    con = db.connect_questions(args.db)
    if args.query == "classes":
        result = db.dicts(
            con,
            "SELECT DISTINCT b.class_number, b.class_level FROM books b ORDER BY b.class_number",
        )
    elif args.query == "subjects":
        result = [r["subject"] for r in db.dicts(
            con, "SELECT DISTINCT subject FROM books WHERE class_number=? AND subject IS NOT NULL ORDER BY subject",
            (args.class_number,))]
    elif args.query == "chapters":
        where = "b.class_number = ?"
        params = [args.class_number]
        if args.subject:
            where += " AND b.subject = ?"
            params.append(args.subject)
        result = db.dicts(
            con,
            "SELECT c.id, c.name, c.chapter_number "
            "FROM chapters c JOIN books b ON c.book_id = b.id "
            f"WHERE {where} ORDER BY c.chapter_number",
            params,
        )
        # availability: question counts per chapter, broken down by type and
        # by (type, marks) — the blueprint buckets are keyed on both. Only
        # ACTIVE questions count (matches what the selector can actually pick),
        # and — if the caller is filtering by paper_tags — only tagged ones.
        qwhere = where + " AND q.is_active != 0"
        qparams = list(params)
        if paper_tags_filter:
            qwhere += " AND (%s)" % " OR ".join("q.paper_tags LIKE ?" for _ in paper_tags_filter)
            qparams += [f'%"{t}"%' for t in paper_tags_filter]
        counts = db.dicts(
            con,
            "SELECT q.chapter_id, q.type, q.marks, COUNT(*) AS n "
            "FROM questions q JOIN chapters c ON q.chapter_id = c.id JOIN books b ON c.book_id = b.id "
            f"WHERE {qwhere} GROUP BY q.chapter_id, q.type, q.marks",
            qparams,
        )
        blocks = db.dicts(
            con,
            "SELECT q.chapter_id, COUNT(DISTINCT q.context_block_id) AS n "
            "FROM questions q JOIN chapters c ON q.chapter_id = c.id JOIN books b ON c.book_id = b.id "
            f"WHERE {qwhere} AND q.context_block_id IS NOT NULL GROUP BY q.chapter_id",
            qparams,
        )
        by, by_marks = {}, {}
        for r in counts:
            by.setdefault(r["chapter_id"], {})
            by[r["chapter_id"]][r["type"]] = by[r["chapter_id"]].get(r["type"], 0) + r["n"]
            m = r["marks"]
            mkey = f"{r['type']}_{int(m) if m == int(m) else m}"
            by_marks.setdefault(r["chapter_id"], {})[mkey] = r["n"]
        blmap = {r["chapter_id"]: r["n"] for r in blocks}
        for ch in result:
            ch["counts"] = by.get(ch["id"], {})
            ch["counts_marks"] = by_marks.get(ch["id"], {})
            ch["case_blocks"] = blmap.get(ch["id"], 0)
            ch["total"] = sum(ch["counts"].values())
    elif args.query == "difficulties":
        result = [r["difficulty"] for r in db.dicts(
            con, "SELECT DISTINCT difficulty FROM questions WHERE difficulty IS NOT NULL ORDER BY difficulty")]
    elif args.query == "buckets":
        # The SAME buckets cbse/select.py will actually draw from for this
        # class+subject — the form uses this to render "Blueprint — questions
        # per section" instead of assuming a fixed marks scheme per type.
        from cbse.select import books_for_class
        from cbse.blueprint import discover_buckets
        books = books_for_class(con, args.class_number, args.subject)
        result = discover_buckets(con, [b["id"] for b in books])
    else:  # paper_tags — the column is a JSON array, so flatten + dedupe in Python
        rows = db.dicts(
            con,
            "SELECT DISTINCT paper_tags FROM questions WHERE paper_tags IS NOT NULL AND is_active != 0",
        )
        tags = set()
        for r in rows:
            try:
                for t in (json.loads(r["paper_tags"]) or []):
                    if t:
                        tags.add(str(t))
            except (TypeError, ValueError):
                continue
        result = sorted(tags)

    json.dump({"query": args.query, "result": result}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
