"""
cli/cbse_pdf.py — CBSE Stage 2b: render the KaTeX HTML to a PDF with weasyprint.

    python3 -m cli.cbse_pdf --html paper.html --out paper.pdf

Run with the omr venv python (has weasyprint). base_url is the HTML's own folder
so any relative asset resolves; KaTeX fonts are referenced by absolute file:// URL
from build_html.js, so they resolve regardless.
"""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from weasyprint import HTML
    HTML(filename=args.html).write_pdf(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
