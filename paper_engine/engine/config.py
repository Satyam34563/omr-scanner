"""
config.py — load and validate the paper config (the contract Laravel produces).

Schema (LOCKED):
  paper-level:
    paper_title, output_name, language (single),
    exam_duration, exam_date,
    selection_mode (paper-wide DEFAULT), random_seed, numbering,
    shortfall_strategy, total_questions, exclude_ids
  each section:
    section_id, total_questions,
    filters: { types, pyq_only, pyq_years, pyq_exams }   (PER-SECTION)
    selection_mode  (optional OVERRIDE of paper default)
    chapters: { "<chapter_id>": count }  or null  (null/blank => equal split)
"""
import json

VALID_MODES = {"repetition_least", "random", "stratified_by_type", "sequential", "pyq_recency"}
VALID_NUMBERING = {"continuous", "per_section"}
VALID_SHORTFALL = {"redistribute", "allow_shortfall"}


class ConfigError(ValueError):
    pass


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"config is not valid JSON: {e}") from e
    return validate(cfg)


def _get_mode(value, where):
    if value is None:
        return None
    if value not in VALID_MODES:
        raise ConfigError(f"{where}: selection_mode '{value}' invalid; expected one of {sorted(VALID_MODES)}")
    return value


def validate(cfg: dict) -> dict:
    """Validate structure + fill defaults. Returns a normalized copy."""
    if not isinstance(cfg, dict):
        raise ConfigError("config root must be a JSON object")

    lang = cfg.get("language")
    if not lang or not isinstance(lang, str):
        raise ConfigError("'language' is required (e.g. 'english' or 'hindi')")

    mode = _get_mode(cfg.get("selection_mode", "repetition_least"), "paper") or "repetition_least"
    numbering = cfg.get("numbering", "continuous")
    if numbering not in VALID_NUMBERING:
        raise ConfigError(f"numbering '{numbering}' invalid; expected {sorted(VALID_NUMBERING)}")
    shortfall = cfg.get("shortfall_strategy", "redistribute")
    if shortfall not in VALID_SHORTFALL:
        raise ConfigError(f"shortfall_strategy '{shortfall}' invalid; expected {sorted(VALID_SHORTFALL)}")

    # sections is OPTIONAL: an empty list means "all sections of the language,
    # equal split of the paper total" (the selector expands it). A non-empty
    # list restricts/overrides specific sections.
    sections = cfg.get("sections") or []
    if not isinstance(sections, list):
        raise ConfigError("'sections' must be a list")

    norm_sections = []
    for i, sec in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(sec, dict):
            raise ConfigError(f"{where} must be an object")
        sid = sec.get("section_id")
        if not isinstance(sid, int):
            raise ConfigError(f"{where}.section_id is required and must be an integer")

        raw_filters = sec.get("filters") or {}
        filters = {
            "types": list(raw_filters.get("types") or []),
            "pyq_only": bool(raw_filters.get("pyq_only", False)),
            "pyq_years": [int(y) for y in (raw_filters.get("pyq_years") or [])],
            "pyq_exams": list(raw_filters.get("pyq_exams") or []),
        }

        chapters = sec.get("chapters")
        # PHP's json_encode turns an empty object {} into an array [], so an
        # empty explicit-chapters map arrives as []. Treat any empty list/dict
        # as "no explicit chapters".
        if isinstance(chapters, (list, dict)) and len(chapters) == 0:
            chapters = None
        if chapters is not None:
            if not isinstance(chapters, dict):
                raise ConfigError(f"{where}.chapters must be an object mapping chapter_id->count, or null")
            norm_ch = {}
            for k, v in chapters.items():
                try:
                    cid = int(k)
                    cnt = int(v)
                except (TypeError, ValueError):
                    raise ConfigError(f"{where}.chapters['{k}'] must be int chapter_id -> int count")
                if cnt < 0:
                    raise ConfigError(f"{where}.chapters['{k}'] count must be >= 0")
                norm_ch[cid] = cnt
            chapters = norm_ch

        total = sec.get("total_questions")
        if total is not None and (not isinstance(total, int) or total < 0):
            raise ConfigError(f"{where}.total_questions must be a non-negative integer or null")

        norm_sections.append({
            "section_id": sid,
            "total_questions": total,
            "filters": filters,
            "selection_mode": _get_mode(sec.get("selection_mode"), where),  # None => inherit paper mode
            "chapters": chapters,
        })

    # A section with neither its own total nor an explicit chapters map draws
    # its share from the paper-level total, so that must exist to split.
    paper_total = cfg.get("total_questions")
    if not norm_sections:
        # "all sections" mode needs a paper total to divide up.
        if paper_total is None:
            raise ConfigError(
                "set a paper-level total_questions (with no sections configured it is "
                "split equally across all sections of the language), or configure at least one section."
            )
    else:
        needs_share = [s for s in norm_sections if s["total_questions"] is None and not s["chapters"]]
        if needs_share and paper_total is None:
            raise ConfigError(
                "some sections have neither total_questions nor a chapters map; set a "
                "paper-level total_questions to split across them (or give each section a total)."
            )

    return {
        "paper_title": cfg.get("paper_title", "Question Paper"),
        "output_name": cfg.get("output_name", "question_paper"),
        "language": lang,
        "exam_duration": cfg.get("exam_duration") or "2 Hours",
        "exam_date": cfg.get("exam_date"),
        "selection_mode": mode,
        "random_seed": cfg.get("random_seed"),
        "numbering": numbering,
        "shortfall_strategy": shortfall,
        "total_questions": cfg.get("total_questions"),
        "exclude_ids": [int(x) for x in (cfg.get("exclude_ids") or [])],
        "sections": norm_sections,
    }
