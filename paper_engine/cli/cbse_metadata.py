"""
cli/cbse_metadata.py — JSON metadata for the CBSE form (classes, chapters,
difficulties). Read-only against questionsitoviii.db.

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
    ap.add_argument("--query", required=True, choices=["classes", "chapters", "difficulties"])
    ap.add_argument("--class-number", type=int)
    args = ap.parse_args()

    con = db.connect_questions(args.db)
    if args.query == "classes":
        result = db.dicts(
            con,
            "SELECT DISTINCT b.class_number, b.class_level, b.subject "
            "FROM books b ORDER BY b.class_number",
        )
    elif args.query == "chapters":
        result = db.dicts(
            con,
            "SELECT c.id, c.name, c.chapter_number "
            "FROM chapters c JOIN books b ON c.book_id = b.id "
            "WHERE b.class_number = ? ORDER BY c.chapter_number",
            (args.class_number,),
        )
    else:  # difficulties
        result = [r["difficulty"] for r in db.dicts(
            con, "SELECT DISTINCT difficulty FROM questions WHERE difficulty IS NOT NULL ORDER BY difficulty")]

    json.dump({"query": args.query, "result": result}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
