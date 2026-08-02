"""
cli/rebuild.py — regenerate a paper's content JSON from an existing one, with
every question re-fetched fresh from the DB (same ids, order, numbering).

    python -m cli.rebuild --db questions.db \
        --content old_paper_content.json --image-base <BANK> --out new_paper_content.json
"""
import argparse
import json

from engine import db, rebuild


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--content", required=True, help="existing paper_content.json to rebuild from")
    ap.add_argument("--image-base", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.content, encoding="utf-8") as f:
        old = json.load(f)

    qcon = db.connect_questions(args.db)
    result = rebuild.rebuild_from_content(qcon, old, args.image_base)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Rebuilt {result['total_questions']} questions -> {args.out}")
    for w in result.get("warnings", []):
        print("  -", w)


if __name__ == "__main__":
    main()
