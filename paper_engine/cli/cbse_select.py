"""
cli/cbse_select.py — CBSE Stage 1: config in -> cbse_paper_content.json out.

    python3 -m cli.cbse_select --db /path/questionsitoviii.db \
        --config cbse_config.json --out cbse_paper_content.json \
        [--usage-db cbse_usage.db] [--no-record]

config (blueprint) — see cbse/blueprint.py:
{
  "paper_title": "...", "class_number": 8, "subject": "Mathematics",
  "exam_duration": "3 Hours",
  "selection_mode": "random",        // random | sequential | repetition_least
  "shortfall_strategy": "redistribute",
  "random_seed": 7,
  "chapters": [1,2,3],               // chapter ids, [] = all
  "difficulty": ["Easy","Medium"],   // [] = all
  "sections": { "A_MCQ": {"count":16}, "C": {"count":6,"chapters":{"1":2,"5":4}} }
}
"""
import argparse
import json

from engine import db, usage
from cbse import select


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--usage-db", default="cbse_usage.db")
    ap.add_argument("--no-record", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    con = db.connect_questions(args.db)
    ucon = usage.connect_usage(args.usage_db)
    usage_map = usage.usage_map(ucon)

    try:
        content, chosen_ids = select.select_paper(con, cfg, usage_map)
    except ValueError as e:
        raise SystemExit(f"invalid configuration: {e}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)

    if not args.no_record and chosen_ids:
        usage.record(ucon, chosen_ids, cfg.get("paper_title", "cbse"))

    total = sum(len(s["questions"]) for s in content["sections"])
    print(f"Selected {total} questions ({content['max_marks']} marks) across {len(content['sections'])} sections.")
    for w in content.get("warnings", []):
        print("  -", w)
    print(f"Wrote {args.out}")
    if args.no_record:
        print("(usage NOT recorded)")


if __name__ == "__main__":
    main()
