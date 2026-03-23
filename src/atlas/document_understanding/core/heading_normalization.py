# src/atlas/document_understanding/core/heading_normalization.py
from __future__ import annotations

import re
from typing import Any


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(len(text), 1)


def _word_count(text: str) -> int:
    return len(norm(text).split())


def is_meta_heading(row: dict[str, Any]) -> bool:
    text_raw = row.get("text") or ""
    text = norm(text_raw).lower()
    if not text:
        return True

    if "doi" in text:
        return True
    if "©" in text_raw:
        return True
    if "vol." in text:
        return True
    if "openchoice" in text:
        return True
    if "creative commons" in text:
        return True
    if "vernacular architecture" in text and re.search(r"\b20\d{2}\b", text):
        return True

    return False


def is_author_line(text: str) -> bool:
    text = norm(text)
    if not text:
        return False

    words = text.split()
    if not 2 <= len(words) <= 8:
        return False

    if any(ch.isdigit() for ch in text):
        return False

    lowered = text.lower()
    if "doi" in lowered or "http" in lowered or "www." in lowered:
        return False

    titlecase_words = 0
    for word in words:
        core = word.strip(",;:()[]")
        if not core:
            continue
        if core[:1].isupper() and (len(core) == 1 or core[1:].islower()):
            titlecase_words += 1

    if titlecase_words >= max(2, len(words) - 1):
        return True

    if " and " in lowered and len(words) <= 8:
        return True

    return False


def is_author_bio(text: str) -> bool:
    text = norm(text)
    lowered = text.lower()

    if len(text.split()) < 8:
        return False

    markers = (
        " is a ",
        " is an ",
        " retired ",
        " he is ",
        " she is ",
        " now ",
        " secretary ",
        " manager ",
        " mathematician ",
        " domestic buildings research group",
    )
    return any(marker in lowered for marker in markers)


def is_contact_line(text: str) -> bool:
    lowered = norm(text).lower()
    if not lowered:
        return False

    if "@" in lowered:
        return True
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        return True
    if " uk;" in lowered or " usa;" in lowered:
        return True

    return False


def is_caption_like(text: str) -> bool:
    lowered = norm(text).lower()
    if not lowered:
        return False

    return (
        lowered.startswith("figure ")
        or lowered.startswith("fig. ")
        or lowered.startswith("table ")
        or lowered.startswith("plate ")
    )


def is_reference_heading(text: str) -> bool:
    lowered = norm(text).lower()
    return lowered in {"references", "bibliography", "works cited", "literature cited"}


def is_appendix_heading(text: str) -> bool:
    lowered = norm(text).lower()
    return lowered in {"appendix", "appendices"}


def is_reference_entry(row: dict[str, Any]) -> bool:
    text = row.get("text") or ""
    collapsed = norm(text)
    lowered = collapsed.lower()
    font_size = _safe_float(row.get("font_size"))
    italic = bool(row.get("italic"))

    if not collapsed:
        return False

    if is_reference_heading(collapsed):
        return False

    if is_caption_like(collapsed):
        return False

    if "@" in lowered:
        return False

    # klassisch: kleine Schrift, oft kursiv, viele bibliographische Marker
    markers = 0
    if "\n" in text:
        markers += 1
    if re.search(r"\(\d{4}\)", text):
        markers += 1
    if " va " in f" {lowered} " or "worksheet" in lowered:
        markers += 1
    if "ed.)" in lowered or "(ed." in lowered:
        markers += 1
    if "pp." in lowered:
        markers += 1
    if "isbn" in lowered:
        markers += 1

    initials_like = bool(re.match(r"^[A-Z]\.\s+[A-Z]\.", collapsed))
    if initials_like:
        markers += 1

    if font_size <= 8.5 and markers >= 1:
        return True

    if italic and font_size <= 8.5 and markers >= 1:
        return True

    if italic and len(collapsed.split()) >= 8 and markers >= 2:
        return True

    return False


def is_fragment_heading(row: dict[str, Any]) -> bool:
    text = norm(row.get("text"))
    if not text:
        return True

    words = text.split()
    font_size = _safe_float(row.get("font_size"))
    italic = bool(row.get("italic"))

    if text.endswith((")", ",", ";")):
        return True

    if italic and font_size < 10.0 and len(words) <= 2:
        return True

    if len(words) == 1:
        token = words[0].strip(".,;:()[]")
        if not token:
            return True
        if token.islower():
            return True
        if italic and font_size <= 10.0 and token[:1].islower():
            return True

    return False


def is_sentence_heading(row: dict[str, Any]) -> bool:
    text = norm(row.get("text"))
    if not text:
        return True

    words = text.split()

    if len(words) == 1:
        return False

    if is_caption_like(text):
        return False

    if text.endswith(":") and len(words) > 5:
        return True

    if text.endswith(".") and len(words) >= 6:
        return True

    if text[:1].islower():
        return True

    if _alpha_ratio(text) < 0.50:
        return True

    return False


def merge_title_lines(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    i = 0

    while i < len(headings):
        current = dict(headings[i])

        if i + 1 < len(headings):
            nxt = headings[i + 1]

            same_font_size = current.get("font_size") == nxt.get("font_size")
            same_page = current.get("page_index") == nxt.get("page_index")
            consecutive = _safe_int(nxt.get("block_index")) == _safe_int(current.get("block_index")) + 1
            both_large = (current.get("font_size") or 0) >= 14 and (nxt.get("font_size") or 0) >= 14

            if same_font_size and same_page and consecutive and both_large:
                current["text"] = f'{norm(current.get("text"))} {norm(nxt.get("text"))}'.strip()
                current["end_block_index"] = nxt.get("block_index")
                result.append(current)
                i += 2
                continue

        result.append(current)
        i += 1

    return result


def filter_headings(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for row in headings:
        text = norm(row.get("text"))

        if not text:
            continue
        if is_meta_heading(row):
            continue
        if is_contact_line(text):
            continue
        if is_caption_like(text):
            continue
        if is_reference_entry(row):
            continue
        if is_author_line(text):
            continue
        if is_author_bio(text):
            continue
        if is_fragment_heading(row):
            continue
        if is_sentence_heading(row):
            continue

        result.append(row)

    return result


def normalize_headings(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings = sorted(headings, key=lambda row: _safe_int(row.get("block_index")))
    headings = merge_title_lines(headings)
    headings = filter_headings(headings)
    return headings
