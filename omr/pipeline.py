"""
The OMR batch-processing pipeline as a plain importable function, shared
by both the CLI (main.py) and the web API (api.py) - so both entry
points run exactly the same logic instead of two copies drifting apart.

run_batch() does everything main.py used to do inline: rasterizes the
scan PDF (or reads a folder of images), perspective-corrects and scores
every sheet, looks up each validated student against the school's
records, and writes the Excel report, combined result PDF, bubble
overlay PDF, and manual-review workbook. It raises a plain exception on
a hard failure (missing layout.json, no scans found, nothing could be
processed) instead of calling sys.exit(), since a library function
shouldn't kill the whole process - the caller (CLI prints + exits; API
turns it into an HTTP error) decides what "failure" means for it.
"""

import glob
import json
import os
from pathlib import Path

import cv2

from omr.pdf_input import rasterize_scan_pdf
from omr.preprocessing import warp_to_canonical
from omr.bubble_detector import detect_answers, detect_roll_number
from omr.answer_key import load_answer_key
from omr.scoring import score_sheet, aggregate_question_stats
from omr.report import build_report
from omr.student_report import build_combined_report
from omr.student_info import fetch_student_info, fetch_student_photo
from omr.manual_review import save_roll_crop, build_manual_review_workbook
from omr.overlay import build_overlay_pdf

IMAGE_EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.tif", "*.tiff", "*.bmp")


def find_scan_files(scans_dir):
    files = []
    for ext in IMAGE_EXTENSIONS:
        files.extend(glob.glob(os.path.join(scans_dir, ext)))
        files.extend(glob.glob(os.path.join(scans_dir, ext.upper())))
    return sorted(set(files))


def load_scan_pages(scans_pdf_path, scans_dir_path, config):
    """Returns a list of (filename, image_bgr) tuples, one per sheet to
    process, in a stable order. Prefers a single combined PDF
    (one page per sheet - the primary, scanner-friendly workflow) and
    falls back to a folder of separate image files only if that PDF
    doesn't exist. Raises FileNotFoundError if neither is available."""
    if scans_pdf_path and os.path.exists(scans_pdf_path):
        pages = rasterize_scan_pdf(scans_pdf_path, dpi=config.get("scan_pdf_dpi", 200))
        stem = Path(scans_pdf_path).stem
        width = max(3, len(str(len(pages))))
        return [(f"{stem}_page{i + 1:0{width}d}", img) for i, img in enumerate(pages)]

    scan_files = find_scan_files(scans_dir_path) if scans_dir_path else []
    if not scan_files:
        raise FileNotFoundError(
            f"No scans found. Put a combined PDF at '{scans_pdf_path}' (one page per sheet), "
            f"or image files in '{scans_dir_path}'."
        )
    return [(os.path.basename(p), cv2.imread(p)) for p in scan_files]


def run_batch(
    scans_pdf_path,
    scans_dir_path,
    answer_key_path,
    config,
    layout,
    output_path,
    reports_pdf_path,
    manual_review_path,
    overlay_pdf_path,
    progress_callback=None,
):
    """
    Runs the full batch: scan -> detect -> score -> student lookup ->
    write every output file. `config` and `layout` are already-loaded
    dicts (not paths), so a caller that keeps them in memory across
    requests (like the web API) doesn't have to re-read them from disk
    every time. `progress_callback(filename, index, total, confirmed_roll,
    summary)`, if given, is called once per sheet as it finishes -
    useful for printing live progress (CLI) or reporting batch progress
    (web API). `confirmed_roll` and `summary` are both None if the
    sheet failed to process at all (e.g. couldn't be warped).

    Returns a dict:
        {
            "output_path": str,
            "reports_pdf_path": str or None,   # None if nothing was resolved yet
            "overlay_pdf_path": str or None,
            "manual_review_path": str or None, # None if nothing needs review
            "num_processed": int,
            "num_resolved": int,
            "num_pending_review": int,
            "warnings": [str, ...],
        }
    Raises RuntimeError if no sheets could be processed at all.
    """
    target_markers = layout.get("markers")

    answer_key, key_warnings = load_answer_key(
        answer_key_path, num_questions=config["num_questions"], marking_scheme=config["marking_scheme"]
    )
    warnings = list(key_warnings)

    scan_pages = load_scan_pages(scans_pdf_path, scans_dir_path, config)

    student_results = []
    all_per_question = []
    pending_entries = []
    overlay_pages = []
    pending_review_dir = config.get("pending_review_dir", "output/pending_review")

    for i, (filename, raw_image) in enumerate(scan_pages):
        try:
            if raw_image is None:
                raise ValueError("could not read page/image data")
            warped = warp_to_canonical(
                raw_image, layout["canonical_width"], layout["canonical_height"], target_markers=target_markers
            )
        except Exception as e:
            warnings.append(f"Failed to process '{filename}': {e}")
            if progress_callback:
                progress_callback(filename, i + 1, len(scan_pages), None, None)
            continue

        # --- Roll number: read from the bubbled grid, then VALIDATE
        # against the school's own student database. Either step
        # failing routes this sheet to manual review instead of
        # guessing - see omr/manual_review.py.
        bubbled_roll, roll_digits, roll_unclear = detect_roll_number(
            warped, layout, fill_threshold=config["fill_threshold"], ambiguous_margin=config["ambiguous_margin"]
        )

        student_info = None
        reason = None
        if roll_unclear or bubbled_roll is None:
            reason = "One or more roll-number digits could not be read clearly."
        else:
            student_info = fetch_student_info(bubbled_roll, config)
            if student_info is None:
                reason = f"Bubbled roll number ({bubbled_roll}) was not found in student records."
            else:
                photo_dir = config.get("student_photo_dir", "output/student_photos")
                student_info["photo_path"] = fetch_student_photo(
                    student_info.get("image_url"), photo_dir, student_info["id_no"]
                )
                if student_info.get("image_url") and not student_info["photo_path"]:
                    warnings.append(
                        f"'{filename}': student photo could not be downloaded from "
                        f"{student_info['image_url']} (network issue or file missing) - "
                        f"PDF will show a 'No Photo' box instead."
                    )

        confirmed_roll = bubbled_roll if (student_info is not None) else None

        if confirmed_roll is None:
            crop_path = save_roll_crop(warped, layout, pending_review_dir, os.path.splitext(filename)[0])
            pending_entries.append({
                "filename": filename,
                "image_path": crop_path,
                "detected_roll": bubbled_roll,
                "reason": reason,
            })
            warnings.append(f"'{filename}': {reason} Sent to manual review.")

        detected = detect_answers(
            warped, layout,
            fill_threshold=config["fill_threshold"],
            ambiguous_margin=config["ambiguous_margin"],
        )
        # 3 or 4 options "filled" on one question is essentially never a
        # genuine answer - it's almost always a scribbled-out/changed
        # answer, a crease, a stain, or heavy ink from a neighboring row
        # bleeding across several bubbles at once. Score it as detected
        # (so it isn't silently dropped), but flag it - it's exactly the
        # kind of question worth a human glancing at the physical sheet for.
        suspect_questions = [q for q, d in detected.items() if len(d["answers"]) >= 3]
        if suspect_questions:
            warnings.append(
                f"'{filename}': question(s) {', '.join(str(q) for q in sorted(suspect_questions))} "
                f"had 3+ bubbles detected as filled - likely a stray mark, crease, or ink bleeding "
                f"in from a neighboring row rather than a genuine answer. Worth checking against the "
                f"physical sheet."
            )

        summary, per_question = score_sheet(detected, answer_key, config["marking_scheme"])
        needs_review = confirmed_roll is None

        # A single-answer question with 2+ bubbles shaded gets resolved
        # to the most confidently-filled one for scoring (see
        # omr/scoring.py) rather than failed outright - worth a note
        # since it means the physical sheet had an accidental double-mark.
        resolved_entries = [pq for pq in per_question if pq.get("resolved")]
        if resolved_entries:
            details = ", ".join(
                f"Q{pq['question']} ({' '.join(pq['raw_student_answer'])} -> {pq['student_answer'][0]})"
                for pq in resolved_entries
            )
            warnings.append(
                f"'{filename}': {len(resolved_entries)} single-answer question(s) had more than one "
                f"bubble shaded - scored using the most confidently-filled option: {details}."
            )

        overlay_pages.append((filename, warped, detected, roll_digits, confirmed_roll or bubbled_roll))

        student_results.append({
            "filename": filename,
            "roll_no": confirmed_roll,
            "summary": summary,
            "per_question": per_question,
            "needs_review": needs_review,
            "student_info": student_info,
        })
        all_per_question.append(per_question)

        if progress_callback:
            progress_callback(filename, i + 1, len(scan_pages), confirmed_roll, summary)

    if not student_results:
        raise RuntimeError("No sheets could be processed.")

    question_stats = aggregate_question_stats(all_per_question, answer_key)
    build_report(output_path, student_results, question_stats, warnings)

    combined_path, skipped = build_combined_report(student_results, config, reports_pdf_path)
    overlay_path = build_overlay_pdf(overlay_pages, layout, overlay_pdf_path)
    manual_review_path_out = build_manual_review_workbook(pending_entries, manual_review_path)

    return {
        "output_path": output_path,
        "reports_pdf_path": combined_path,
        "overlay_pdf_path": overlay_path,
        "manual_review_path": manual_review_path_out,
        "num_processed": len(student_results),
        "num_resolved": len(student_results) - len(skipped),
        "num_pending_review": len(pending_entries),
        "warnings": warnings,
    }


def load_config_and_layout(config_path, layout_path):
    """Small shared helper: load config.json and layout.json from disk,
    raising a clear error if layout.json hasn't been generated yet."""
    with open(config_path) as f:
        config = json.load(f)
    if not os.path.exists(layout_path):
        raise FileNotFoundError(
            f"Layout file '{layout_path}' not found. Generate it automatically from the master PDF:\n"
            f"  python tools/auto_generate_layout.py --pdf {config.get('sheet_pdf', '<sheet>.pdf')} --output {layout_path}"
        )
    with open(layout_path) as f:
        layout = json.load(f)
    return config, layout
