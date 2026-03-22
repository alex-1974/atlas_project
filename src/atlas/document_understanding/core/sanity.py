# src/atlas/document_understanding/core/sanity.py

from __future__ import annotations
from typing import Any


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def is_page_furniture(row: dict[str, Any]) -> bool:
    return any(
        row.get(k)
        for k in (
            "is_page_furniture",
            "page_number_like",
            "running_header_like",
            "running_footer_like",
            "repeated_across_pages",
            "repeated_same_parity",
            "is_top_band",
            "is_bottom_band",
        )
    )


def is_noise(row: dict[str, Any]) -> bool:
    return row.get("role") in {"noise", "caption", "reference"}


def is_doi_like(row: dict[str, Any]) -> bool:
    text = norm(row.get("text")).lower()
    return row.get("semantic_doi") or text.startswith("doi:")


def is_contact(row: dict[str, Any]) -> bool:
    text = norm(row.get("text")).lower()
    return (
        "@" in text
        or "http://" in text
        or "https://" in text
        or "www." in text
    )


def is_sentence(row: dict[str, Any]) -> bool:
    text = norm(row.get("text"))
    words = text.split()

    if len(words) >= 16:
        return True

    if text.endswith(".") and len(words) >= 8:
        return True

    if text[:1].islower() and len(words) >= 5:
        return True

    return False


def is_author(row: dict[str, Any]) -> bool:
    text = norm(row.get("text"))
    words = text.split()

    if not (2 <= len(words) <= 10):
        return False

    if any(c.isdigit() for c in text):
        return False

    centered = row.get("centeredness", 0) >= 0.6
    near_top = (row.get("doc_y_ratio") or 0) <= 0.25

    titlecase = sum(
        1 for w in words
        if w[:1].isupper() and w[1:].islower()
    )

    return centered and near_top and titlecase >= max(2, len(words) - 1)
