"""
textfix.py — Krutidev->Unicode legacy-font artifact cleanup for Hindi text.

Ported verbatim from the original paper_pipeline/select_questions.py — this table
is battle-tested against the Hindi source books. Only unambiguous garbles are
mapped, longest/most-specific first. Never touches image paths.
"""
import re

KRUTIDEV_FIXES = [
    ("राष्Vª", "राष्ट्र"),
    ("दृषि्V", "दृष्टि"),
    ("Vª", "ट्र"),          # Vªाम->ट्राम
    ("टª", "ट्र"),           # मेटªो->मेट्रो
    ("बãपुत्र", "ब्रह्मपुत्र"),
    ("ã", "ह्म"),            # ब्रãाण्ड->ब्रह्माण्ड
    ("11वेंद्ध", "11वें)"),
    ("वैंळ", "कैं"),          # वैंळपाकोला->कैंपाकोला
    ("वैळ", "कै"),           # वैळसे->कैसे
    ("व्रूळ", "क्रू"),        # व्रूळर->क्रूर
    ("वू्रळ", "क्रू"),
    ("वूळ", "कू"),           # अनुवूळल->अनुकूल
    ("वुळ", "कु"),           # वुळछ->कुछ
    ("वृळ", "कृ"),           # कलावृळति->कलाकृति
    ("वेळ", "के"),           # वेळवल->केवल, उनवेळ->उनके
    ("पेंळ", "फें"),          # पेंळक->फेंक
    ("पेळं", "फें"),
    ("पैळ", "फै"),           # पैळला->फैला
    ("पेळ", "फे"),           # पेळरें->फेरें
    ("Iय", "प्य"),           # Iयार->प्यार, Iयास->प्यास
    ("शु:", "शुरू"),          # शु: की गई->शुरू की गई
]
# lone V after a Devanagari half-form / vowel sign -> ट (स्पष्V, ऊँV, ...)
_V_RE = re.compile(r"(?<=[ऀ-ॿ])V")
# lone ':' directly followed by a Devanagari letter -> रू (:प->रूप, ज:री->जरूरी)
_COLON_RE = re.compile(r":(?=[क-ह])")
# leaked "<line-number> द्य" junk (Krutidev '|' danda + verse numbers) -> drop
_DIGIT_DYA_RE = re.compile(r"\s*\d+\s*द्य")


def fix_devanagari_text(s):
    if not s or not isinstance(s, str):
        return s
    for bad, good in KRUTIDEV_FIXES:
        s = s.replace(bad, good)
    s = _V_RE.sub("ट", s)
    s = _COLON_RE.sub("रू", s)
    s = _DIGIT_DYA_RE.sub("", s)
    return s


def deep_fix_devanagari(obj):
    """In-place fix of every string value in a question dict (stem, options,
    explanation, context block text) — skips image paths and non-strings."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "image" or k.endswith("_images"):
                continue  # never touch file paths
            if isinstance(v, str):
                obj[k] = fix_devanagari_text(v)
            else:
                deep_fix_devanagari(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                obj[i] = fix_devanagari_text(v)
            else:
                deep_fix_devanagari(v)
