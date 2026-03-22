# src/atlas/document_understanding/layers/section_tree.py
from __future__ import annotations

from typing import Any

from atlas.document_understanding.core.heading_normalization import (
    is_appendix_heading,
    is_reference_heading,
    normalize_headings,
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except:
        return default


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


# ---------------------------------------------------------
# Candidate Expansion (bestehend)
# ---------------------------------------------------------

def _estimate_body_font(blocks: list[dict]) -> float:
    sizes = [_safe_float(b.get("font_size")) for b in blocks if b.get("font_size")]
    if not sizes:
        return 10.0
    sizes = sorted(sizes)
    return sizes[len(sizes) // 2]


def _is_typographic_heading(b: dict, body_font: float) -> bool:
    size = _safe_float(b.get("font_size"))
    italic = bool(b.get("italic"))
    text = _norm(b.get("text"))

    if not text:
        return False

    if size >= body_font + 1.5:
        return True

    if italic and len(text.split()) <= 5 and size >= body_font - 0.2:
        return True

    return False


def _is_score_heading(b: dict) -> bool:
    heading = _safe_float(b.get("heading_score"))
    body = _safe_float(b.get("body_score"))
    noise = _safe_float(b.get("noise_score"))
    caption = _safe_float(b.get("caption_score"))
    reference = _safe_float(b.get("reference_score"))

    return heading >= 0.35 and heading > body and heading > noise and heading > caption and heading > reference


def _collect_heading_candidates(blocks: list[dict]) -> list[dict]:
    body_font = _estimate_body_font(blocks)

    candidates = []

    for b in blocks:
        role = (b.get("role") or "").lower()

        if role == "heading":
            candidates.append(b)
            continue

        if _is_score_heading(b):
            candidates.append(b)
            continue

        if _is_typographic_heading(b, body_font):
            candidates.append(b)
            continue

    return candidates


# ---------------------------------------------------------
# Style Model
# ---------------------------------------------------------

def _style_key(h: dict[str, Any]) -> tuple:
    return (
        round(_safe_float(h.get("font_size")), 1),
        bool(h.get("italic")),
    )


def _compute_style_levels(headings: list[dict]) -> dict:
    styles = {}

    for h in headings:
        key = _style_key(h)
        styles.setdefault(key, []).append(h)

    sorted_styles = sorted(
        styles.keys(),
        key=lambda k: (-k[0], k[1]),
    )

    return {style: i + 1 for i, style in enumerate(sorted_styles)}


# ---------------------------------------------------------
# Title Detection
# ---------------------------------------------------------

def _detect_title(headings: list[dict]) -> dict | None:
    if not headings:
        return None

    max_font = max(_safe_float(h.get("font_size")) for h in headings)

    candidates = [h for h in headings if _safe_float(h.get("font_size")) == max_font]
    candidates.sort(key=lambda h: _safe_int(h.get("block_index")))

    return candidates[0] if candidates else None


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def compute_section_tree(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)

    # -----------------------------------------------------
    # Step 1: Candidate Expansion
    # -----------------------------------------------------

    candidates = _collect_heading_candidates(blocks)

    raw_headings = [
        {
            "block_id": b.get("block_id"),
            "block_index": b.get("block_index"),
            "page_index": b.get("page_index"),
            "text": b.get("text"),
            "font_size": b.get("font_size"),
            "italic": b.get("italic"),
        }
        for b in candidates
    ]

    print("\n--- RAW CANDIDATES ---")
    for h in raw_headings:
        print(h)

    # -----------------------------------------------------
    # Step 2: Normalisierung
    # -----------------------------------------------------

    headings = normalize_headings(raw_headings)

    print("\n--- NORMALIZED HEADINGS ---")
    for h in headings:
        print(h)

    if not headings:
        repo.store_section_tree(document_id, [])
        return

    # -----------------------------------------------------
    # Step 3: Titel erkennen & entfernen
    # -----------------------------------------------------

    title = _detect_title(headings)

    structural_headings = [
        h for h in headings if h is not title
    ]

    # -----------------------------------------------------
    # Step 4: Level Mapping
    # -----------------------------------------------------

    style_levels = _compute_style_levels(structural_headings)

    # -----------------------------------------------------
    # Step 5: Tree bauen (stabil)
    # -----------------------------------------------------

    rows = []
    stack = []
    node_id = 1

    for i, h in enumerate(structural_headings):
        text = _norm(h.get("text"))

        level = style_levels[_style_key(h)]

        # harte strukturelle Korrektur (generisch!)
        if is_reference_heading(text) or is_appendix_heading(text):
            level = 1

        block_index = _safe_int(h.get("block_index"))
        end_block = _safe_int(h.get("end_block_index"), block_index)

        title_text = text or f"Section {i+1}"

        while stack and stack[-1]["level"] >= level:
            stack.pop()

        parent_id = stack[-1]["section_node_id"] if stack else None

        node = {
            "section_node_id": node_id,
            "parent_section_node_id": parent_id,
            "heading_block_id": h.get("block_id"),
            "start_block_index": block_index,
            "end_block_index": end_block,
            "page_start": h.get("page_index"),
            "page_end": h.get("page_index"),
            "level": level,
            "role": "heading",
            "section_number": None,
            "title": title_text,
            "title_normalized": title_text.lower(),
            "is_numbered": False,
            "confidence": None,
            "source": "hierarchical_v1",
        }

        rows.append(node)
        stack.append(node)
        node_id += 1

    repo.store_section_tree(document_id, rows)
