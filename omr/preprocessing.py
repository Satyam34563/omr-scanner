"""
Image preprocessing for OMR sheets.

Takes a raw photo/scan of a filled answer sheet and produces a
perspective-corrected image at the exact canonical pixel size used by
layout.json, so bubble coordinates calibrated once - automatically,
from the clean master PDF, see tools/auto_generate_layout.py - line up
reliably no matter how the photo was framed, rotated, or scaled.

This sheet (html_answer_sheet/omr_sheet.pdf) prints 4 solid black
registration squares near its corners specifically so this step can be
fully automatic: find_registration_markers() looks for them directly,
one per image-corner region, which is far more precise and robust than
guessing the paper's outer edge from a generic contour search.
find_sheet_corners() (the old generic "biggest quadrilateral" approach)
is kept only as a fallback for photos where a marker is out of frame or
too damaged to detect.
"""

import cv2
import numpy as np

# The 4 registration squares are printed at 6mm - a tiny, fixed
# fraction of the page regardless of scan resolution (on the 1654x2339
# @200dpi canonical master, a 6mm square is ~47x47px, ~2230px^2, which
# is ~0.06% of the full page area). Filtering candidate blobs by that
# fraction of the FULL PAGE - not by a percentage of the (much bigger)
# per-corner SEARCH region below - is what actually stays correct
# however large a search region is used. A wide search region (needed
# to tolerate a skewed/cropped photo) previously meant "1% of the
# search box" was actually a bigger area than the real marker itself,
# so the true marker was silently rejected as "too small" while a much
# bigger, similarly square-ish dark shape elsewhere in the same search
# box (e.g. the school logo) wrongly passed every check instead.
MARKER_AREA_FRACTION_OF_PAGE = 0.0006
MARKER_AREA_TOLERANCE = 3.5   # generous +/- around that fraction (real print/scan scale varies)


def _order_points(pts):
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.array(pts, dtype="float32")
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]      # top-left has smallest sum
    rect[2] = pts[np.argmax(s)]      # bottom-right has largest sum
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]   # top-right has smallest difference
    rect[3] = pts[np.argmax(diff)]   # bottom-left has largest difference
    return rect


def find_sheet_corners(image):
    """
    Locate the outer edge of the answer sheet in a photo and return its
    4 corner points, ordered TL, TR, BR, BL. Returns None if no suitable
    quadrilateral contour is found (e.g. sheet edge not visible / poor
    lighting) so the caller can fall back to using the full image.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)
    edged = cv2.dilate(edged, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    image_area = image.shape[0] * image.shape[1]

    for c in contours[:8]:
        if cv2.contourArea(c) < 0.3 * image_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            return _order_points(approx.reshape(4, 2))

    return None


def _best_square_in_region(gray, x0, y0, x1, y1, area_range, anchor):
    """Find the solid, roughly-square dark blob in a region that's
    correctly SIZED like a registration marker (area_range, an absolute
    pixel-area window derived from the known 6mm marker size and the
    whole page's area - see MARKER_AREA_FRACTION_OF_PAGE above) and,
    among any that qualify, the one CLOSEST to `anchor` (the true sheet
    corner this region was searched for, in full-image coordinates) -
    not simply the largest. A marker sits right at the sheet's corner
    by design, so distance-to-corner is what correctly picks it out
    over a similarly square-ish but more inset dark shape (e.g. the
    school logo) that a generously sized search region can also catch.
    Returns (center_x, center_y) in FULL-IMAGE coordinates, or None."""
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    blurred = cv2.GaussianBlur(roi, (5, 5), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area, max_area = area_range
    ax, ay = anchor
    best, best_dist = None, float("inf")
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        if bw == 0 or bh == 0:
            continue
        aspect = bw / float(bh)
        if not (0.7 <= aspect <= 1.4):
            continue  # markers are square, not elongated text/lines
        extent = area / float(bw * bh)
        if extent < 0.75:
            continue  # markers are solid filled squares, not outlines
        cx, cy = x0 + bx + bw / 2, y0 + by + bh / 2
        dist = (cx - ax) ** 2 + (cy - ay) ** 2
        if dist < best_dist:
            best_dist = dist
            best = (cx, cy)
    return best


def find_registration_markers(image, search_frac=0.30):
    """
    Find the 4 solid corner registration squares printed on the sheet
    by searching a fixed fraction of each image corner independently.
    Returns 4 points ordered TL, TR, BR, BL, or None if any corner's
    marker can't be confidently found (e.g. that corner of the sheet
    is out of frame or in shadow) - the caller should fall back to
    find_sheet_corners() in that case.

    Assumes the photo is roughly right-side-up (not upside-down or
    rotated 90 degrees) - this sheet's 4 markers are visually
    identical squares, so orientation can't be recovered from them
    alone.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sw, sh = int(w * search_frac), int(h * search_frac)

    expected_area = MARKER_AREA_FRACTION_OF_PAGE * (w * h)
    area_range = (expected_area / MARKER_AREA_TOLERANCE, expected_area * MARKER_AREA_TOLERANCE)

    regions = {
        "tl": (0, 0, sw, sh, (0, 0)),
        "tr": (w - sw, 0, w, sh, (w, 0)),
        "br": (w - sw, h - sh, w, h, (w, h)),
        "bl": (0, h - sh, sw, h, (0, h)),
    }

    found = {}
    for key, (x0, y0, x1, y1, anchor) in regions.items():
        marker = _best_square_in_region(gray, x0, y0, x1, y1, area_range, anchor)
        if marker is None:
            return None
        found[key] = marker

    return np.array([found["tl"], found["tr"], found["br"], found["bl"]], dtype="float32")


def warp_to_canonical(image, canonical_width, canonical_height, target_markers=None):
    """
    Perspective-correct `image` to a canonical_width x canonical_height
    image.

    If `target_markers` (the {"tl": [x,y], "tr": ..., "br": ..., "bl": ...}
    dict from layout.json) is supplied, this first tries to detect the
    sheet's own registration markers and warps so they land exactly on
    those target coordinates - the precise, preferred path. Falls back
    to detecting the paper's outer edge, then to a plain resize.
    """
    if target_markers is not None:
        corners = find_registration_markers(image)
        if corners is not None:
            dst = np.array([
                target_markers["tl"], target_markers["tr"],
                target_markers["br"], target_markers["bl"],
            ], dtype="float32")
            matrix = cv2.getPerspectiveTransform(corners, dst)
            return cv2.warpPerspective(image, matrix, (canonical_width, canonical_height))

    quad = find_sheet_corners(image)
    if quad is not None:
        dst = np.array([
            [0, 0], [canonical_width - 1, 0],
            [canonical_width - 1, canonical_height - 1], [0, canonical_height - 1],
        ], dtype="float32")
        matrix = cv2.getPerspectiveTransform(quad, dst)
        return cv2.warpPerspective(image, matrix, (canonical_width, canonical_height))

    return cv2.resize(image, (canonical_width, canonical_height))


def load_and_normalize(image_path, canonical_width, canonical_height, target_markers=None):
    """Load an image file from disk and return the canonical warped image."""
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    return warp_to_canonical(image, canonical_width, canonical_height, target_markers=target_markers)
