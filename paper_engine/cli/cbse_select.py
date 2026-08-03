"""
cli/cbse_select.py — CBSE Stage 1: config in -> cbse_paper_content.json out.

    python3 -m cli.cbse_select --db /path/questionsitoviii.db \
        --config cbse_config.json --out cbse_paper_content.json

config.json (blueprint):
{
  "paper_title": "Class VIII Mathematics — Sample Paper",
  "class_number": 8,
  "subject": "Mathematics",
  "exam_duration": "3 Hours",
  "selection_mode": "random",         // random | sequential
  "random_seed": 7,
  "chapters": [1,2,3],                 // chapter ids, or [] / omit = all
  "difficulty": ["Easy","Medium"],    // or [] / omit = all
  "sections": { "A": {"count": 16}, "E": {"count": 3} }   // override default counts/marks
}
"""
import argparse
import json

from engine import db
from cbse import select


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    con = db.connect_questions(args.db)
    result = select.select_paper(con, cfg)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(s["questions"]) for s in result["sections"])
    print(f"Selected {total} questions ({result['max_marks']} marks) across {len(result['sections'])} sections.")
    for w in result.get("warnings", []):
        print("  -", w)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
