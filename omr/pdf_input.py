"""
Reads a whole batch of scanned/photographed answer sheets from a
single combined PDF - the natural output of a scanner's "scan to
PDF"/ADF feature, or of stacking several phone photos into one file -
so nobody has to save out and manage a folder of separate image files
per batch.

Each PAGE of the PDF is treated as one filled-in answer sheet, in page
order. Rendering uses the same `pdftoppm` (poppler) tool already
relied on to render the master sheet in tools/auto_generate_layout.py,
just without `-singlefile` so every page is rasterized.

The rasterization DPI here is independent of `render_dpi` in
config.json (which is tied to the pixel coordinates baked into
layout.json) - marker-based perspective correction re-maps whatever
resolution comes out of this step onto the canonical layout, exactly
like it already does for arbitrarily-sized photos.
"""

import re
import subprocess
import tempfile
from pathlib import Path

import cv2


def rasterize_scan_pdf(pdf_path, dpi=200):
    """Returns a list of BGR image arrays (as read by cv2.imread), one
    per page of `pdf_path`, in page order. Raises RuntimeError if the
    PDF can't be rasterized at all (e.g. poppler not installed,
    corrupt file)."""
    with tempfile.TemporaryDirectory() as tmp:
        out_prefix = str(Path(tmp) / "page")
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), out_prefix],
                check=True, capture_output=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "pdftoppm not found - install poppler-utils (see README) to read scans from a PDF."
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Could not rasterize '{pdf_path}': {e.stderr.decode(errors='replace')}")

        pages = sorted(
            Path(tmp).glob("page-*.png"),
            key=lambda p: int(re.search(r"-(\d+)$", p.stem).group(1)),
        )
        if not pages:
            raise RuntimeError(f"'{pdf_path}' has no pages poppler could rasterize.")

        images = []
        for page_path in pages:
            img = cv2.imread(str(page_path))
            if img is None:
                raise RuntimeError(f"Could not read rasterized page '{page_path.name}'.")
            images.append(img)
        return images
