# src/atlas/document_understanding/core/heading_candidates.py

from __future__ import annotations

from typing import Any


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


# ------------------------------------------------------------
# BASE SIGNALS (existing logic)
# ------------------------------------------------------------

def _is_score_heading(block: dict[str, Any]) -> bool:
    return (
        _safe_float(block.get("heading_score")) >= 0.35
        and _safe_float(block.get("heading_score")) > _safe_float(block.get("body_score"))
        and _safe_float(block.get("heading_score")) > _safe_float(block.get("noise_score"))
    )


def _is_typographic_heading(block: dict[str, Any], body_font: float) -> bool:
    size = _safe_float(block.get("font_size"))
    italic = bool(block.get("italic"))
    text = _norm(block.get("text"))

    if not text:
        return False

    if size >= body_font + 1.5:
        return True

    if italic and len(text.split()) <= 6:
        return True

    return False


# ------------------------------------------------------------
# NEW: EXPANSION SIGNALS
# ------------------------------------------------------------

def _looks_like_section_boundary(prev_block, block) -> bool:
    """
    Detect transitions like:
    paragraph → heading-like line
    """
    if not prev_block:
        return False

    prev_len = len(_norm(prev_block.get("text")))
    cur_len = len(_norm(block.get("text")))

    if prev_len > 80 and cur_len < 60:
        return True

    return False


def _is_short_standalone(block) -> bool:
    text = _norm(block.get("text"))
    if not text:
        return False

    words = text.split()

    return (
        1 <= len(words) <= 6
        and not text.endswith(".")
    )


def _font_transition(prev_block, block) -> bool:
    if not prev_block:
        return False

    prev_size = _safe_float(prev_block.get("font_size"))
    cur_size = _safe_float(block.get("font_size"))

    return cur_size > prev_size + 0.8


def _is_not_noise(block) -> bool:
    text = _norm(block.get("text")).lower()

    if not text:
        return False

    if "figure" in text:
        return False

    if "doi" in text:
        return False

    if len(text) < 3:
        return False

    return True


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def collect_heading_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not blocks:
        return []

    # estimate body font
    sizes = [_safe_float(b.get("font_size")) for b in blocks if b.get("font_size")]
    body_font = sorted(sizes)[len(sizes)//2] if sizes else 10.0

    candidates: list[dict[str, Any]] = []

    for i, block in enumerate(blocks):
        prev_block = blocks[i-1] if i > 0 else None

        text = _norm(block.get("text"))
        if not text:
            continue

        role = str(block.get("role") or "").lower()

        # ----------------------------------
        # STRONG SIGNALS
        # ----------------------------------
        if role == "heading":
            candidates.append(block)
            continue

        if _is_score_heading(block):
            candidates.append(block)
            continue

        if _is_typographic_heading(block, body_font):
            candidates.append(block)
            continue

        # ----------------------------------
        # NEW: EXPANSION LAYER
        # ----------------------------------

        if not _is_not_noise(block):
            continue

        # short standalone lines
        if _is_short_standalone(block) and _looks_like_section_boundary(prev_block, block):
            candidates.append(block)
            continue

        # font jump
        if _font_transition(prev_block, block) and _is_short_standalone(block):
            candidates.append(block)
            continue

    return candidates
