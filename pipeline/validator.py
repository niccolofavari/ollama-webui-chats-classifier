"""
Validation and sanitization of LLM-produced extraction and classification records.

Two groups of functions:

  sanitize_extraction(raw, chat_id, title)
      Called after phase1 LLM output. Returns a clean dict that always has
      every required field with the correct type — never raises.

  sanitize_classification(raw, valid_cats, valid_tags, valid_int_types, chat_id)
      Called after phase4 LLM output. Validates against the approved taxonomy
      vocabulary and corrects / logs every deviation — never raises.

Both functions log every correction they make so problems are traceable.
"""

from __future__ import annotations

import re
from typing import Any

from logger import get_logger

log = get_logger("validator")


# ── Constants ────────────────────────────────────────────────────────────────

FALLBACK_TITLE = "No title"
FALLBACK_LANGUAGE = "unknown"
FALLBACK_INTERACTION_TYPE = "other"
FALLBACK_CATEGORY = "miscellaneous"  # last resort if taxonomy has no misc

VALID_CONFIDENCE_VALUES = {"high", "medium", "low", "alta", "media", "bassa"}

# Characters allowed in a tag slug
_SLUG_RE = re.compile(r"[^a-z0-9\-_]")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _coerce_str(value: Any, field: str, chat_id: str, fallback: str = "") -> str:
    """Return value as a non-empty stripped string, or fallback."""
    if isinstance(value, list):
        joined = " ".join(str(v) for v in value if v).strip()
        if joined:
            log.warning(
                "[%s] field '%s' was a list, joined to string: %r", chat_id, field, joined[:80]
            )
            return joined
        log.warning("[%s] field '%s' was an empty list, using fallback %r", chat_id, field, fallback)
        return fallback
    if not isinstance(value, str):
        coerced = str(value).strip() if value is not None else ""
        log.warning(
            "[%s] field '%s' had type %s, coerced to string: %r",
            chat_id, field, type(value).__name__, coerced[:80],
        )
        return coerced or fallback
    stripped = value.strip()
    if not stripped:
        log.debug("[%s] field '%s' is empty, using fallback %r", chat_id, field, fallback)
        return fallback
    return stripped


def _coerce_str_list(value: Any, field: str, chat_id: str, max_items: int = 30) -> list[str]:
    """Return value as a flat list of non-empty stripped strings."""
    if isinstance(value, str):
        # Model sometimes returns a comma-separated string instead of a list
        items = [v.strip() for v in value.split(",") if v.strip()]
        log.warning(
            "[%s] field '%s' was a string, split to %d items", chat_id, field, len(items)
        )
        return items[:max_items]
    if not isinstance(value, list):
        log.warning(
            "[%s] field '%s' had unexpected type %s, using []",
            chat_id, field, type(value).__name__,
        )
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, (int, float)):
            result.append(str(item))
        elif item is not None:
            log.debug("[%s] field '%s': skipping non-string item %r", chat_id, field, item)
    return result[:max_items]


def _coerce_bool(value: Any, field: str, chat_id: str, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        if value.lower() in ("true", "yes", "1", "si", "sì"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
    log.warning(
        "[%s] field '%s' had unexpected value %r, using %s",
        chat_id, field, value, fallback,
    )
    return fallback


# ── Public API ───────────────────────────────────────────────────────────────

def sanitize_title(title: Any) -> str:
    """
    Return a clean, non-empty title string.
    Strips whitespace; replaces blank/None with FALLBACK_TITLE.
    """
    if not title:
        return FALLBACK_TITLE
    clean = str(title).strip()
    return clean if clean else FALLBACK_TITLE


def sanitize_extraction(raw: dict, chat_id: str = "", title: str = "") -> dict:
    """
    Validate and sanitize the dict returned by the LLM in phase1.

    Guarantees the returned dict has these keys with correct types:
        summary         str   (non-empty)
        topics          list[str]
        entities        list[str]
        user_intent     str
        interaction_type str
        language        str
        multi_topic     bool
        quality_note    str | None

    All corrections are logged at WARNING level so they are visible in the
    log file and can be grep'd during debugging.
    """
    if not isinstance(raw, dict):
        log.error(
            "[%s] extraction result is not a dict (type=%s), building empty record",
            chat_id, type(raw).__name__,
        )
        raw = {}

    label = chat_id or title or "unknown"

    summary = _coerce_str(raw.get("summary"), "summary", label, fallback="(no summary)")
    topics = _coerce_str_list(raw.get("topics", []), "topics", label, max_items=20)
    entities = _coerce_str_list(raw.get("entities", []), "entities", label, max_items=20)
    user_intent = _coerce_str(raw.get("user_intent"), "user_intent", label)
    interaction_type = _coerce_str(
        raw.get("interaction_type"), "interaction_type", label,
        fallback=FALLBACK_INTERACTION_TYPE,
    )
    multi_topic = _coerce_bool(raw.get("multi_topic"), "multi_topic", label, fallback=False)

    # language: normalize list → single string
    lang_raw = raw.get("language", "")
    if isinstance(lang_raw, list):
        lang_raw = lang_raw[0] if lang_raw else ""
        log.warning("[%s] 'language' was a list, using first element: %r", label, lang_raw)
    language = _coerce_str(lang_raw, "language", label, fallback=FALLBACK_LANGUAGE)

    quality_note_raw = raw.get("quality_note")
    if quality_note_raw in (None, "null", "none", "None", ""):
        quality_note: str | None = None
    else:
        quality_note = _coerce_str(quality_note_raw, "quality_note", label)

    return {
        "summary": summary,
        "topics": topics,
        "entities": entities,
        "user_intent": user_intent,
        "interaction_type": interaction_type,
        "language": language,
        "multi_topic": multi_topic,
        "quality_note": quality_note,
    }


def sanitize_classification(
    raw: dict,
    valid_cats: list[str],
    valid_tags: list[str],
    valid_int_types: list[str],
    chat_id: str = "",
    title: str = "",
) -> dict:
    """
    Validate and sanitize the dict returned by the LLM in phase4.

    Guarantees:
        macro_category   str  — always one of valid_cats
        subcategory      str | None
        tags             list[str]  — only values in valid_tags
        interaction_type str  — always one of valid_int_types
        confidence       str  — one of: high/medium/low (or alta/media/bassa)
        ambiguity_note   str | None

    Unknown category → falls back to last valid_cat (expected to be 'misc').
    Unknown tags → dropped and logged.
    Unknown interaction_type → falls back to first valid_int_type.
    """
    if not isinstance(raw, dict):
        log.error(
            "[%s] classification result is not a dict (type=%s), using fallback category",
            chat_id, type(raw).__name__,
        )
        raw = {}

    label = chat_id or title or "unknown"
    fallback_cat = valid_cats[-1] if valid_cats else FALLBACK_CATEGORY
    fallback_int = valid_int_types[0] if valid_int_types else FALLBACK_INTERACTION_TYPE

    # ── macro_category ───────────────────────────────────────────────────────
    macro = _coerce_str(raw.get("macro_category"), "macro_category", label)
    validation_notes: list[str] = []

    if macro not in valid_cats:
        # Try partial match (model sometimes returns "category-name" vs "cat-name")
        match = next(
            (v for v in valid_cats if v in macro or macro in v), None
        )
        if match:
            log.warning(
                "[%s] macro_category %r not in vocab, corrected to %r via partial match",
                label, macro, match,
            )
            validation_notes.append(f"category corrected from '{macro}' to '{match}'")
            macro = match
        else:
            log.warning(
                "[%s] macro_category %r not in vocab and no partial match, "
                "falling back to '%s'",
                label, macro, fallback_cat,
            )
            validation_notes.append(
                f"unknown category '{macro}', assigned fallback '{fallback_cat}'"
            )
            macro = fallback_cat

    # ── subcategory ──────────────────────────────────────────────────────────
    sub_raw = raw.get("subcategory")
    subcategory: str | None = None
    if sub_raw and str(sub_raw).strip().lower() not in ("null", "none", ""):
        subcategory = str(sub_raw).strip()

    # ── tags ─────────────────────────────────────────────────────────────────
    raw_tags = _coerce_str_list(raw.get("tags", []), "tags", label, max_items=10)
    valid_tag_set = set(valid_tags)
    accepted_tags: list[str] = []
    dropped_tags: list[str] = []
    for tag in raw_tags:
        if tag in valid_tag_set:
            accepted_tags.append(tag)
        else:
            dropped_tags.append(tag)
    if dropped_tags:
        log.warning(
            "[%s] %d tag(s) not in controlled vocabulary, dropped: %s",
            label, len(dropped_tags), dropped_tags,
        )
        validation_notes.append(f"dropped invalid tags: {dropped_tags}")

    # ── interaction_type ─────────────────────────────────────────────────────
    int_type = _coerce_str(
        raw.get("interaction_type"), "interaction_type", label, fallback=fallback_int
    )
    if int_type not in valid_int_types:
        log.warning(
            "[%s] interaction_type %r not in vocab, using fallback '%s'",
            label, int_type, fallback_int,
        )
        validation_notes.append(
            f"interaction_type corrected from '{int_type}' to '{fallback_int}'"
        )
        int_type = fallback_int

    # ── confidence ───────────────────────────────────────────────────────────
    confidence = _coerce_str(raw.get("confidence"), "confidence", label, fallback="medium")
    if confidence.lower() not in VALID_CONFIDENCE_VALUES:
        log.warning("[%s] unexpected confidence value %r, defaulting to 'medium'", label, confidence)
        confidence = "medium"

    # ── ambiguity_note ───────────────────────────────────────────────────────
    amb_raw = raw.get("ambiguity_note")
    ambiguity_note: str | None = None
    if amb_raw and str(amb_raw).strip().lower() not in ("null", "none", ""):
        ambiguity_note = str(amb_raw).strip()

    result = {
        "macro_category": macro,
        "subcategory": subcategory,
        "tags": accepted_tags,
        "interaction_type": int_type,
        "confidence": confidence,
        "ambiguity_note": ambiguity_note,
    }
    if validation_notes:
        result["_validation_notes"] = validation_notes

    return result
