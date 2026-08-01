"""
cli/select.py — Stage 1: config in -> paper_content.json out.

Run from the project root:

    python3 -m cli.select \
        --db /path/questions.db \
        --config config.json \
        --image-base /path/to/QUESTION_BANK \
        --out paper_content.json \
        --usage-db paper_usage.db

By default the chosen questions are recorded in the sidecar usage DB (drives
repetition-least). Pass --no-record for previews/drafts that shouldn't "burn"
questions.
"""
import argparse
import json
import sys

from engine import db, usage, selector, output
from engine.config import load_config, ConfigError


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to questions.db (read-only)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--image-base", required=True, help="folder containing images/ (QUESTION_BANK root)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--usage-db", default="paper_usage.db")
    ap.add_argument("--no-record", action="store_true", help="don't record usage history")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    qcon = db.connect_questions(args.db)
    ucon = usage.connect_usage(args.usage_db)
    usage_map = usage.usage_map(ucon)

    sections_out, chosen_ids, warnings = selector.select_paper(qcon, usage_map, cfg)
    result = output.build_output(cfg, sections_out, warnings, args.image_base)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not args.no_record and chosen_ids:
        usage.record(ucon, chosen_ids, cfg["output_name"])

    print(f"Selected {result['total_questions']} questions across {len(sections_out)} sections.")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print("  -", w)
    print(f"\nWrote {args.out}")
    if args.no_record:
        print("(usage NOT recorded: --no-record)")


if __name__ == "__main__":
    main()
