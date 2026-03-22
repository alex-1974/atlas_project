# src/atlas/document_understanding/core/structural_sanity.py

from __future__ import annotations
from typing import Any


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def is_valid_heading_candidate(row: dict[str, Any]) -> bool:
    text = norm(row.get("text"))
    if not text:
        return False

    words = text.split()

    # --- harte Ausschlüsse ---
    if len(words) <= 1:
        return False

    if len(words) > 18:
        return False

    if text.endswith((")", ",", ";")):
        return False

    if any(c.isdigit() for c in text[:3]):
        return False

    # --- Satzfilter ---
    if text.endswith(".") and len(words) >= 6:
        return False

    if text[:1].islower():
        return False

    # --- Zeichenfilter ---
    alpha = sum(c.isalpha() for c in text)
    if alpha < 0.5 * len(text):
        return False

    return True


def role_allows_heading(role_row: dict[str, Any]) -> bool:
    heading = role_row.get("heading_score") or 0
    body = role_row.get("body_score") or 0
    noise = role_row.get("noise_score") or 0
    caption = role_row.get("caption_score") or 0
    reference = role_row.get("reference_score") or 0

    # Dominanzregel
    if heading < max(body, noise, caption, reference):
        return False

    # Mindestschwelle
    if heading < 0.25:
        return False

    return True


def is_author(role_row: dict[str, Any]) -> bool:
    title = role_row.get("title_score") or 0
    heading = role_row.get("heading_score") or 0

    # Titel dominiert, aber nicht stark genug → Autor
    return title > heading and title > 0.4


def reject_by_roles(role_row: dict[str, Any]) -> bool:
    if is_author(role_row):
        return True

    if (role_row.get("reference_score") or 0) > 0.4:
        return True

    if (role_row.get("caption_score") or 0) > 0.4:
        return True

    if (role_row.get("noise_score") or 0) > 0.5:
        return True

    return False
