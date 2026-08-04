"""
cli/cbse_pdf.py — CBSE Stage 2b: render the KaTeX HTML to a PDF with weasyprint.

    python3 -m cli.cbse_pdf --html paper.html --out paper.pdf

Run with the omr venv python (has weasyprint). base_url is the HTML's own folder
so any relative asset resolves; KaTeX fonts are referenced by absolute file:// URL
from build_html.js, so they resolve regardless.

If the HTML contains <!--CHUNK--> markers (build_html.js inserts them in the
solutions doc), the body is rendered as separate chunks and the pages are
concatenated — weasyprint's layout cost grows super-linearly with document
size, so chunking keeps big documents fast and memory-bounded.
"""
import argparse
import os
import sys
import time

CHUNK_MARK = "<!--CHUNK-->"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from weasyprint import HTML

    with open(args.html, encoding="utf-8") as f:
        raw = f.read()
    base = os.path.dirname(os.path.abspath(args.html))

    if CHUNK_MARK in raw and "<body>" in raw and "</body>" in raw:
        head, rest = raw.split("<body>", 1)
        body, tail = rest.rsplit("</body>", 1)
        parts = body.split(CHUNK_MARK)
        docs = []
        for i, part in enumerate(parts):
            t0 = time.time()
            chunk = head + "<body>" + part + "</body>" + tail
            docs.append(HTML(string=chunk, base_url=base).render())
            print(f"  chunk {i + 1}/{len(parts)} rendered in {time.time() - t0:.1f}s", file=sys.stderr)
        pages = [p for d in docs for p in d.pages]
        docs[0].copy(pages).write_pdf(args.out)
    else:
        HTML(filename=args.html).write_pdf(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
