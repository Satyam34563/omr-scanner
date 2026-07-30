"""
OMR Checker - local web API.

Wraps the same pipeline main.py uses (omr/pipeline.py's run_batch())
behind a small HTTP API, so another application on the same server -
e.g. a Laravel app - can call it over plain HTTP instead of shelling
out to a Python script. Meant to be reached ONLY from other processes
on the same machine (see "Security" below), not exposed to the public
internet directly.

Endpoints:
    GET  /health    - liveness check, returns {"status": "ok"}
    POST /process   - upload a scans PDF + answer key, get back a ZIP
                       of every output file (results.xlsx,
                       student_reports.pdf, bubble_overlay.pdf,
                       manual_review.xlsx + its roll-grid crop images)

Each request gets its own temporary working directory, so concurrent
requests from different callers never share or overwrite each other's
output files. Student photos ARE still cached in the shared
`student_photo_dir` from config.json across requests (same school ->
same students -> no point re-downloading each time), but everything
else is request-scoped and deleted once the response has been sent.

Security:
    Run this bound to 127.0.0.1 only (see run_api.sh / the systemd unit
    in DEPLOY.md) - it has no authentication of its own, and processes
    files containing students' names, photos, and roll numbers. Your
    existing web app's login should be what actually gates access;
    this API should never be reachable from outside the server itself.

Run directly for local testing:
    uvicorn api:app --host 127.0.0.1 --port 8001
"""

import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask

from omr.pipeline import run_batch, load_config_and_layout

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
LAYOUT_PATH = PROJECT_ROOT / "layout.json"

app = FastAPI(title="OMR Checker API")

# Loaded once at startup - config.json/layout.json describe the fixed
# sheet template, not anything that changes per request.
_config, _layout = load_config_and_layout(str(CONFIG_PATH), str(LAYOUT_PATH))


@app.get("/health")
def health():
    return {"status": "ok"}


def _save_upload(upload: UploadFile, dest_path: Path):
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(upload.file, f)


def _zip_outputs(work_dir: Path, result: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key in ("output_path", "reports_pdf_path", "overlay_pdf_path", "manual_review_path"):
            path = result.get(key)
            if path and os.path.exists(path):
                zf.write(path, arcname=os.path.basename(path))
        # Roll-grid crop images referenced by manual_review.xlsx, if any,
        # so the reviewer can actually see them without a separate download.
        pending_dir = work_dir / "pending_review"
        if pending_dir.exists():
            for img_path in pending_dir.iterdir():
                zf.write(img_path, arcname=f"pending_review/{img_path.name}")
        zf.writestr(
            "summary.json",
            json.dumps({
                "num_processed": result["num_processed"],
                "num_resolved": result["num_resolved"],
                "num_pending_review": result["num_pending_review"],
                "warnings": result["warnings"],
            }, indent=2),
        )
    buf.seek(0)
    return buf


@app.post("/process")
async def process(
    scans_pdf: UploadFile = File(..., description="Combined PDF, one scanned sheet per page"),
    answer_key: UploadFile = File(..., description="Excel answer key (.xlsx)"),
):
    if not scans_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "scans_pdf must be a .pdf file")
    if not answer_key.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "answer_key must be an .xlsx file")

    work_dir = Path(tempfile.mkdtemp(prefix="omr_job_"))
    try:
        scans_pdf_path = work_dir / "scans.pdf"
        answer_key_path = work_dir / "answer_key.xlsx"
        _save_upload(scans_pdf, scans_pdf_path)
        _save_upload(answer_key, answer_key_path)

        # Student photos are worth caching across requests (same
        # school's students recur); everything else is scoped to this
        # one job's temp directory so concurrent requests can't collide.
        job_config = dict(_config)
        job_config["pending_review_dir"] = str(work_dir / "pending_review")

        result = run_batch(
            scans_pdf_path=str(scans_pdf_path),
            scans_dir_path=None,
            answer_key_path=str(answer_key_path),
            config=job_config,
            layout=_layout,
            output_path=str(work_dir / "results.xlsx"),
            reports_pdf_path=str(work_dir / "student_reports.pdf"),
            manual_review_path=str(work_dir / "manual_review.xlsx"),
            overlay_pdf_path=str(work_dir / "bubble_overlay.pdf"),
        )
    except (FileNotFoundError, RuntimeError) as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(400, str(e))
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(500, f"Processing failed: {e}")

    zip_buf = _zip_outputs(work_dir, result)
    cleanup = BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=omr_results.zip"},
        background=cleanup,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    # Never leak a raw stack trace to the caller - this may be
    # reachable by a Laravel app you don't fully control the input to.
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
