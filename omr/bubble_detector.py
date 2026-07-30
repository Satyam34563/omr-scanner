"""
Bubble fill detection.

Given a perspective-corrected sheet image and a `layout.json` describing
the pixel center of every option bubble (produced once, automatically,
by tools/auto_generate_layout.py), this module decides which option(s)
(if any) the student filled in for each of the 100 questions, and which
digit was bubbled at each roll-number position.

WHY QUESTION DETECTION ISN'T JUST "SAMPLE THE PIXELS AT (x, y)":
Real, hand-filled sheets don't line up with layout.json's coordinates
as precisely as the synthetic test sheets used during development.
Paper isn't perfectly flat, a 4-corner perspective correction can't
undo any small nonlinear print/scan distortion, and students don't
fill bubbles perfectly centered - on a real scan, a genuinely filled
bubble's ink can easily be shifted 15-25+ pixels from where the layout
expects it (verified empirically against a real test scan: even a
bubble's own PRINTED outline ring, which is machine-printed and
therefore not "sloppy," can end up that far from its layout.json
coordinate in some page regions). A small fixed-radius sample exactly
at (x, y) simply misses ink that's shifted that much - it reads as
blank even though the bubble is clearly filled a short distance away.

So detect_answers() doesn't sample a fixed spot. Instead it:
  1. Finds every ink blob on the whole page ONE TIME (connected
     components on the binarized image).
  2. For every option bubble, finds the CLOSEST nearby blob within a
     safe search radius - safe meaning smaller than half the spacing
     to the next bubble, so a blob can't plausibly belong to two
     bubbles at once. Assignment is greedy nearest-first across the
     WHOLE question grid, so if two bubbles are both in range of the
     same blob, only the truly closer one claims it.
  3. Classifies the assigned blob as "filled ink" vs. "just the
     bubble's own empty printed ring" using its size (a printed ring
     is a thin, mostly-hollow annulus with a small, very consistent
     area; genuine ink fills - even light or partial ones - cover
     noticeably more of their bounding box). The size split between
     "ring" and "fill" is computed adaptively from THIS sheet's own
     blob-size distribution (the biggest gap in the sorted areas),
     since how dark/complete a fill looks depends on pen/pencil,
     scan quality, and printing - not one fixed number that would
     work for every batch.

detect_answers() supports questions with more than one filled bubble:
every option assigned a "fill"-classified blob is selected, independently
of the others, so a student darkening both C and D reads as ["C", "D"].

detect_roll_number() deliberately keeps the older, simpler fixed-spot
measurement instead of the blob-matching approach above: the roll grid
packs its 10 stacked value bubbles per digit far more tightly than the
100-question grid (rows only ~40px apart there, against a ~20px bubble
radius), so neighboring bubbles' printed rings routinely touch and
merge into one big connected component - there's no way to tell which
of the 10 rows is filled from blob shape alone. Measuring darkness
directly in a small circle at each known position sidesteps that
merging entirely, and is the approach that's been reliable for roll
numbers in practice. Each digit position can only hold one value, so
it picks the single darkest bubble per position and flags a position
as ambiguous if two values are shaded similarly dark.
"""

import cv2
import numpy as np

# --- Question-grid (blob-matching) detection -------------------------

# Ink blobs smaller than this (relative to a bubble's own printed
# area) are noise - print/scan dust, JPEG artifacts, thin line
# fragments - not real marks.
MIN_BLOB_AREA_FRACTION = 0.05
# Ink blobs bigger than this aren't a single bubble's mark - they're
# structural page elements (section rules, table borders, header
# text) that happen to have a blob centroid within range of a bubble.
MAX_BLOB_AREA_FRACTION = 3.0

# How far (as a fraction of the tightest spacing between any two
# question bubbles on the sheet) to search for a bubble's nearest ink
# blob. Greedy nearest-first assignment resolves any conflict where
# two bubbles are both in range of the same blob, so this doesn't need
# to be as conservative as a naive fixed-radius sample - but going much
# past this starts trading missed fills (false blanks) for stray ink
# from a heavily-marked neighboring row bleeding into the wrong bubble
# (false multi-selects), so this is a deliberately moderate middle
# ground, not the largest radius that was tried.
SEARCH_RADIUS_FRACTION = 0.5

# Fallback ring/fill area split (as a fraction of a bubble's nominal
# printed area, pi * radius^2) used only if a sheet doesn't have
# enough filled bubbles yet to find a reliable gap in its own blob-size
# distribution (e.g. a nearly-blank test sheet).
DEFAULT_FILL_AREA_FRACTION = 0.55

# --- Roll-grid (fixed-spot) detection ---------------------------------

# The stored bubble_radius in layout.json is the bubble's full printed
# radius, which includes its thin ink border ring. Measuring fill over
# the FULL radius picks up that ring even on a blank bubble (baseline
# ~0.30 fill ratio - too close to a real fill for a reliable margin).
# Shrinking the measurement ROI to ~75% of the radius samples mostly
# interior pixels instead, dropping the empty-bubble baseline to ~0.02-0.06
# while filled bubbles still read ~1.0 - a much safer separation.
FILL_MEASURE_FRACTION = 0.75


def binarize(warped_bgr):
    """Convert the warped color image to a binary (dark=foreground) image."""
    gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    # Otsu threshold: pixels darker than the automatic threshold become
    # foreground (255) in the binary image.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def _question_slots(layout):
    """Every answer-bubble position as (key, x, y), key=(q_num, opt)."""
    slots = []
    for q_str, options in layout.get("bubbles", {}).items():
        q_num = int(q_str)
        for opt, (x, y) in options.items():
            slots.append(((q_num, opt), float(x), float(y)))
    return slots


def _min_spacing(slots):
    """Smallest center-to-center distance between any two bubble slots
    on the sheet - used to size a search radius that can never
    plausibly reach past a neighboring bubble."""
    if len(slots) < 2:
        return 40.0
    pts = np.array([[x, y] for _, x, y in slots])
    min_d = np.inf
    n = len(pts)
    chunk = 200
    for i0 in range(0, n, chunk):
        block = pts[i0:i0 + chunk]
        diff = block[:, None, :] - pts[None, :, :]
        dist = np.sqrt((diff ** 2).sum(axis=2))
        for row_i in range(block.shape[0]):
            global_i = i0 + row_i
            row = np.delete(dist[row_i], global_i)
            if row.size:
                min_d = min(min_d, row.min())
    return float(min_d) if np.isfinite(min_d) else 40.0


def _assign_blobs(slots, stats, centroids, n_labels, search_radius, min_area, max_area):
    """Greedy nearest-first matching between bubble slots and nearby
    ink blobs: every (slot, blob) pair within `search_radius` is a
    candidate, processed closest-first, and once a slot or a blob is
    claimed neither can be claimed again. This is what lets a bubble's
    ink be recognized even when it's shifted well off the slot's exact
    layout.json coordinate, without two different slots being able to
    claim the same mark."""
    candidate_blobs = [
        i for i in range(1, n_labels)
        if min_area <= stats[i, cv2.CC_STAT_AREA] <= max_area
    ]
    if not candidate_blobs:
        return {}

    blob_xy = centroids[candidate_blobs]
    candidates = []
    for key, x, y in slots:
        diff = blob_xy - np.array([x, y])
        dist = np.sqrt((diff ** 2).sum(axis=1))
        for local_i, d in enumerate(dist):
            if d <= search_radius:
                candidates.append((d, key, candidate_blobs[local_i]))
    candidates.sort(key=lambda c: c[0])

    assigned = {}
    claimed_slots, claimed_blobs = set(), set()
    for dist, key, blob_i in candidates:
        if key in claimed_slots or blob_i in claimed_blobs:
            continue
        area = int(stats[blob_i, cv2.CC_STAT_AREA])
        w = int(stats[blob_i, cv2.CC_STAT_WIDTH])
        h = int(stats[blob_i, cv2.CC_STAT_HEIGHT])
        extent = area / (w * h) if w * h else 0.0
        assigned[key] = {"area": area, "extent": round(extent, 3), "dist": round(float(dist), 1)}
        claimed_slots.add(key)
        claimed_blobs.add(blob_i)

    return assigned


def _auto_fill_area_threshold(areas, default, max_threshold, min_gap_fraction=0.12):
    """Finds the split between "empty bubble ring" and "genuine ink
    fill" from the sheet's OWN distribution of assigned blob areas,
    instead of trusting one fixed number for every batch (pencil vs.
    pen, pressure, scan quality, and print darkness all shift where
    that line actually falls). Returns the midpoint of the single
    biggest gap in the sorted areas (searched only in the 25th-97th
    percentile range, so a handful of extreme outliers can't create a
    spurious "gap"); falls back to `default` if there isn't a large
    enough gap to be confident (e.g. a sheet with too few filled
    bubbles yet to show a clear split).

    On a sheet where most genuinely blank bubbles never get a blob
    assigned at all (too small to pass the min-area filter, rather
    than merging with something else), the assigned population can end
    up being almost ALL genuine fills - and the biggest gap in THAT
    distribution just splits heavier ink from lighter ink, not fill
    from blank, which was observed to silently produce a threshold
    higher than a bubble's own full nominal area (i.e. demanding MORE
    ink than a completely covered bubble could ever contain to count
    as "filled" at all - impossible, and it misread the majority of a
    real sheet's genuine marks as blank). `max_threshold` guards
    against exactly that: the chosen split can never exceed it,
    regardless of what the gap search finds."""
    vals = sorted(a for a in areas if a > 0)
    if len(vals) < 12:
        return min(default, max_threshold)

    lo = max(1, int(len(vals) * 0.25))
    hi = min(len(vals) - 1, int(len(vals) * 0.97))
    if hi <= lo:
        return min(default, max_threshold)

    best_gap, best_split = 0.0, None
    for i in range(lo, hi):
        gap = vals[i + 1] - vals[i]
        if gap > best_gap:
            best_gap = gap
            best_split = (vals[i] + vals[i + 1]) / 2.0

    min_gap = min_gap_fraction * (vals[hi] - vals[lo] + 1e-6)
    if best_split is None or best_gap < max(min_gap, default * 0.15):
        return min(default, max_threshold)
    return min(best_split, max_threshold)


def detect_answers(warped_bgr, layout, fill_threshold=0.42, ambiguous_margin=0.12):
    """
    Returns a dict: {question_number(int): result_dict} where result_dict has:
      - "answers": sorted list of selected options, e.g. ["C"], ["C", "D"], or [] if left blank
      - "ratios": {"A": 0.03, "B": 0.81, ...}  (for debugging/audit - area of the
        matched ink blob relative to a bubble's nominal printed area, capped at 1.0;
        0.0 if no ink blob was found near that option at all)

    `fill_threshold`/`ambiguous_margin` are accepted for a stable call
    site but unused here: whether an option counts as filled is decided
    per-sheet from its own ink-blob size distribution (see
    _auto_fill_area_threshold), not a fixed global cutoff - see the
    module docstring for why.
    """
    binary = binarize(warped_bgr)

    radius = layout.get("bubble_radius", 20)

    # Morphological opening (erode then dilate) breaks the thin,
    # anti-aliased bridge that can otherwise fuse a bubble's own
    # printed ring together with the option letter (A/B/C/D) printed
    # inside it into ONE connected blob - confirmed on a real, noisy
    # scan where shrinking the bubbles 30% moved that letter glyph
    # close enough to the ring for the two to routinely touch after
    # binarization, misreading a genuinely blank bubble as a partial
    # ink fill (its ring+letter blob landing well inside the "filled"
    # size range). A real fill is a substantial, solid blob that
    # survives this operation with its area mostly intact; a thin
    # bridge does not. The kernel size is sized off the bubble's own
    # radius (rather than a fixed pixel constant) so it stays
    # correctly calibrated if the bubble size or scan DPI changes
    # again - a low-contrast/noisy real scan needed a notably bigger
    # kernel than a clean synthetic one to fully sever the bridge.
    kernel_size = max(3, int(round(radius * 0.5)) | 1)  # odd, >=3
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    n_labels, _, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    nominal_area = np.pi * (radius ** 2)
    min_area = MIN_BLOB_AREA_FRACTION * nominal_area
    max_area = MAX_BLOB_AREA_FRACTION * nominal_area

    slots = _question_slots(layout)
    search_radius = SEARCH_RADIUS_FRACTION * _min_spacing(slots)
    assigned = _assign_blobs(slots, stats, centroids, n_labels, search_radius, min_area, max_area)

    default_threshold = DEFAULT_FILL_AREA_FRACTION * nominal_area
    # A blob can only plausibly BE a genuine fill if it takes no more
    # ink than the bubble's own full printed area - so the threshold
    # for "counts as filled" can never be asked to exceed nominal_area
    # itself, however the gap search below turns out.
    fill_threshold_area = _auto_fill_area_threshold(
        [v["area"] for v in assigned.values()], default_threshold, max_threshold=nominal_area
    )

    results = {}
    for q_str, options in layout["bubbles"].items():
        q_num = int(q_str)
        ratios = {}
        selected = []
        for opt in ["A", "B", "C", "D"]:
            if opt not in options:
                continue
            info = assigned.get((q_num, opt))
            area = info["area"] if info else 0
            ratios[opt] = round(min(1.0, area / nominal_area), 4)
            if area >= fill_threshold_area:
                selected.append(opt)
        results[q_num] = {"answers": sorted(selected), "ratios": ratios}

    return results


def _measure_radius(layout):
    radius = layout.get("bubble_radius", 13)
    return max(4, int(radius * FILL_MEASURE_FRACTION))


def _fill_ratio(binary_img, cx, cy, radius):
    """Fraction of dark (foreground) pixels inside a circular ROI."""
    h, w = binary_img.shape
    x0, x1 = max(0, cx - radius), min(w, cx + radius)
    y0, y1 = max(0, cy - radius), min(h, cy + radius)
    roi = binary_img[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0

    mask = np.zeros(roi.shape, dtype=np.uint8)
    cv2.circle(mask, (min(cx, x1) - x0, min(cy, y1) - y0), radius, 255, -1)
    mask = mask[: roi.shape[0], : roi.shape[1]]

    masked = cv2.bitwise_and(roi, roi, mask=mask)
    filled_px = cv2.countNonZero(masked)
    total_px = cv2.countNonZero(mask)
    if total_px == 0:
        return 0.0
    return filled_px / total_px


def detect_roll_number(warped_bgr, layout, fill_threshold=0.42, ambiguous_margin=0.12):
    """
    Reads the bubbled roll number (see the "Roll Number" grid on
    html_answer_sheet/omr_sheet.pdf: 6 digit positions x values 0-9
    each).

    Returns (roll_str_or_None, per_digit_results, needs_review: bool).
    per_digit_results is a list of {"position", "value", "flag", "ratios"}
    ordered by digit position (most significant digit first).
    """
    roll_grid = layout.get("roll_grid")
    if not roll_grid:
        return None, [], True

    binary = binarize(warped_bgr)
    radius = _measure_radius(layout)
    per_digit = []
    digits = []
    needs_review = False

    for pos_str in sorted(roll_grid["bubbles"].keys(), key=int):
        values = roll_grid["bubbles"][pos_str]
        ratios = {}
        for val_str, (x, y) in values.items():
            ratios[val_str] = round(_fill_ratio(binary, int(x), int(y), radius), 4)

        sorted_vals = sorted(ratios.items(), key=lambda kv: kv[1], reverse=True)
        best_val, best_ratio = sorted_vals[0]
        second_ratio = sorted_vals[1][1] if len(sorted_vals) > 1 else 0.0

        if best_ratio < fill_threshold:
            value, flag = None, "blank"
        elif (best_ratio - second_ratio) < ambiguous_margin:
            value, flag = None, "multiple"
        else:
            value, flag = best_val, None

        if flag is not None:
            needs_review = True
        digits.append(value)
        per_digit.append({"position": int(pos_str), "value": value, "flag": flag, "ratios": ratios})

    roll_str = "".join(digits) if all(d is not None for d in digits) else None
    if roll_str is None:
        needs_review = True

    return roll_str, per_digit, needs_review
