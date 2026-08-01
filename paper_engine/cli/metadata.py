"""
cli/metadata.py — JSON metadata endpoint for the Laravel cascading form.

Laravel calls this (via Process) as the user fills the form; every response is
JSON on stdout with post-filter counts. Run from the project root:

    python3 -m cli.metadata --db /path/questions.db --query sections \
        --spec '{"language":"english"}'

queries: languages | sections | chapters | types | pyq_exams | pyq_years | pool
`spec` is a JSON object with any FilterSpec fields:
    language, section_ids, chapter_ids, types, pyq_only, pyq_years,
    pyq_exams, exclude_ids
"""
import argparse
import json
import sys

from engine import db, metadata
from engine.filters import FilterSpec

QUERIES = {
    "languages": lambda con, spec: metadata.languages(con),
    "sections": metadata.sections,
    "chapters": metadata.chapters,
    "types": metadata.types,
    "pyq_exams": metadata.pyq_exams,
    "pyq_years": metadata.pyq_years,
    "pool": lambda con, spec: {"pool_size": metadata.pool_size(con, spec)},
}


def spec_from_dict(d: dict) -> FilterSpec:
    d = d or {}
    return FilterSpec(
        language=d.get("language"),
        section_ids=list(d.get("section_ids") or []),
        chapter_ids=list(d.get("chapter_ids") or []),
        types=list(d.get("types") or []),
        pyq_only=bool(d.get("pyq_only", False)),
        pyq_years=list(d.get("pyq_years") or []),
        pyq_exams=list(d.get("pyq_exams") or []),
        exclude_ids=list(d.get("exclude_ids") or []),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--query", required=True, choices=sorted(QUERIES))
    ap.add_argument("--spec", default="{}", help="JSON filter spec")
    args = ap.parse_args()

    try:
        spec = spec_from_dict(json.loads(args.spec))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"bad --spec JSON: {e}"}), file=sys.stderr)
        sys.exit(2)

    con = db.connect_questions(args.db)
    result = QUERIES[args.query](con, spec)
    json.dump({"query": args.query, "result": result}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
