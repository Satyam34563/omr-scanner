"""
Looks up a student's official record from the school's own system, by
the roll number bubbled on the OMR sheet:

    GET https://dlcs.managemyschools.in/api/student/info/{roll}

Confirmed response shape (flat JSON, no auth needed from this
network):
    {"id_no":"260471","name":"DILKHUSH KUMAR","father_name":"KISHORI  KUMAR",
     "image":"dlcs_IMG_0927.jpg","class":"III","section":"A","roll":18}

"image" is just a filename; the actual photo lives at
    https://dlcs.managemyschools.in/upload/student_images/{image}
It's optional - not every student has one uploaded, so its absence
doesn't fail validation the way a missing name/class/etc. would.

An unknown/invalid roll number returns an empty body. Note "roll" in
the response is the student's roll number WITHIN their class/section
(a small number), which is a different thing from the 6-digit roll
number bubbled on the sheet (that one is looked up as `id_no` - the
student's unique ID/admission number).

This lookup doubles as validation: if it returns nothing, the bubbled
roll number doesn't correspond to a real student, which is treated the
same as "couldn't read the roll number" - both route the sheet to
manual review (see omr/manual_review.py) rather than guessing.
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://dlcs.managemyschools.in/api/student/info"
DEFAULT_IMAGE_BASE = "https://dlcs.managemyschools.in/upload/student_images"
REQUIRED_FIELDS = ["id_no", "name", "father_name", "class", "roll", "section"]


def fetch_student_info(roll_no, config, timeout=8):
    """Returns a dict with id_no/name/father_name/class/roll/section/
    image_url (image_url may be None), or None if the roll number
    doesn't resolve to a real student (not found, API unreachable,
    timeout, or a malformed response)."""
    if not roll_no:
        return None

    base = config.get("student_info_api_base", DEFAULT_API_BASE)
    url = f"{base.rstrip('/')}/{roll_no}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    if not raw:
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict) or not all(
        data.get(f) not in (None, "") for f in REQUIRED_FIELDS
    ):
        return None

    image_name = data.get("image")
    # "no_image.jpg" (served from a different path than real per-student
    # photos, e.g. /upload/no_image.jpg vs /upload/student_images/<file>)
    # is the system's generic placeholder for a student with no photo
    # uploaded - treat it the same as no image at all rather than
    # downloading and displaying a generic silhouette as if it were real.
    is_placeholder = bool(image_name) and "no_image" in image_name.lower()
    image_base = config.get("student_image_api_base", DEFAULT_IMAGE_BASE)
    image_url = f"{image_base.rstrip('/')}/{image_name}" if (image_name and not is_placeholder) else None

    return {
        "id_no": str(data["id_no"]),
        "name": str(data["name"]).strip(),
        "father_name": str(data["father_name"]).strip(),
        "class": str(data["class"]),
        "roll": str(data["roll"]),
        "section": str(data["section"]),
        "image_url": image_url,
    }


def fetch_student_photo(image_url, out_dir, id_no, timeout=8):
    """Downloads a student's photo to `out_dir/{id_no}.<ext>` and
    returns the local path, or None if there's no image_url or the
    download fails for any reason (missing file, timeout, etc.) -
    a missing photo is never treated as a validation failure."""
    if not image_url:
        return None

    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    if not data:
        return None

    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(image_url)[1] or ".jpg"
    out_path = os.path.join(out_dir, f"{id_no}{ext}")
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path
