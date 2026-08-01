"""
cli/export.py — build the OMR answer-key .xlsx and the metadata .pdf from a
paper_content.json. Run with a Python that has openpyxl + weasyprint (the OMR
venv by default; see services.paper.export_python):

    python -m cli.export --content paper_content.json \
        --out-xlsx answer_key.xlsx --out-pdf metadata.pdf [--marks 1.5 --negative 0.25]
"""
import argparse
import json

from engine import exports


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--out-xlsx", required=True)
    ap.add_argument("--out-pdf", required=True)
    ap.add_argument("--marks", type=float, default=1.5)
    ap.add_argument("--negative", type=float, default=0.25)
    args = ap.parse_args()

    with open(args.content, encoding="utf-8") as f:
        content = json.load(f)

    exports.write_answer_key_xlsx(content, args.out_xlsx, args.marks, args.negative)
    exports.write_metadata_pdf(content, args.out_pdf)
    print(f"wrote {args.out_xlsx} and {args.out_pdf}")


if __name__ == "__main__":
    main()
