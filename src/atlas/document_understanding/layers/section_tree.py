# src/atlas/document_understanding/layers/section_tree.py

from __future__ import annotations

from typing import Any

from atlas.document_understanding.core.heading_candidates import collect_heading_candidates
from atlas.document_understanding.core.heading_normalization import (
    is_appendix_heading,
    is_reference_heading,
    normalize_headings,
)
from atlas.document_understanding.core.style_model import build_style_model


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _style_key(h: dict[str, Any]) -> tuple[float, bool]:
    return (
        round(_safe_float(h.get("font_size")), 1),
        bool(h.get("italic")),
    )


def _fetch_zone_map(repo, document_id: str) -> dict[int, str]:
    zones = repo.fetch_semantic_zones(document_id)
    mapping: dict[int, str] = {}

    for z in zones:
        start = _safe_int(z.get("start_block_index"))
        end = _safe_int(z.get("end_block_index"))
        zone = z.get("zone_type")

        for i in range(start, end + 1):
            mapping[i] = zone

    return mapping


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()

    for r in rows:
        key = (_safe_int(r.get("block_index")), _norm(r.get("text")).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)

    return out


def _detect_title(headings: list[dict[str, Any]]) -> dict | None:
    if not headings:
        return None

    max_font = max(_safe_float(h.get("font_size")) for h in headings)
    candidates = [h for h in headings if _safe_float(h.get("font_size")) == max_font]
    candidates.sort(key=lambda h: _safe_int(h.get("block_index")))
    return candidates[0] if candidates else None


def _is_top_level_text(text: str) -> bool:
    lowered = _norm(text).lower()
    if not lowered:
        return False

    return (
        "conclusion" in lowered
        or "acknowledg" in lowered
        or is_reference_heading(lowered)
        or is_appendix_heading(lowered)
    )


def _looks_like_terminal_major_heading(h: dict[str, Any]) -> bool:
    """
    Generic fallback for late-document major headings even when glyph decoding
    obscures the exact text (e.g. small-caps ligature garbage).
    """
    idx = _safe_int(h.get("block_index"))
    italic = bool(h.get("italic"))
    font_size = _safe_float(h.get("font_size"))
    heading_score = _safe_float(h.get("heading_score"))
    text = _norm(h.get("text"))
    word_count = len(text.split()) if text else 0

    return (
        idx >= 120
        and not italic
        and font_size >= 10.0
        and heading_score >= 0.5
        and 1 <= word_count <= 4
    )


def _is_front_meta_like(h: dict[str, Any]) -> bool:
    """
    Exclude only likely title/front-matter leftovers from the front zone,
    not genuine early section headings.
    """
    text = _norm(h.get("text"))
    if not text:
        return True

    word_count = len(text.split())
    font_size = _safe_float(h.get("font_size"))
    italic = bool(h.get("italic"))
    heading_score = _safe_float(h.get("heading_score"))

    if 1 <= word_count <= 4 and not italic and heading_score >= 0.5:
        return False

    if italic and word_count <= 3 and font_size <= 10.0:
        return False

    if font_size >= 14.0:
        return True

    return heading_score < 0.55


def _final_level(h: dict[str, Any], zone: str, style_levels: dict[tuple[float, bool], int]) -> int:
    text = _norm(h.get("text"))

    if zone == "back":
        return 1

    if _is_top_level_text(text) or _looks_like_terminal_major_heading(h):
        return 1

    level = style_levels.get(_style_key(h), 1)

    # generic bias: non-italic short headings tend to be major;
    # italic short headings tend to be subordinate.
    italic = bool(h.get("italic"))
    word_count = len(text.split()) if text else 0

    if not italic and 1 <= word_count <= 5:
        level = min(level, 1)
    elif italic and 1 <= word_count <= 6:
        level = max(level, 2)

    return level


def compute_section_tree(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)
    zone_map = _fetch_zone_map(repo, document_id)

    candidates = collect_heading_candidates(blocks)

    raw = _dedupe(
        [
            {
                "block_id": b.get("block_id"),
                "block_index": b.get("block_index"),
                "page_index": b.get("page_index"),
                "text": b.get("text"),
                "font_size": b.get("font_size"),
                "italic": b.get("italic"),
                "heading_score": b.get("heading_score"),
                "body_score": b.get("body_score"),
            }
            for b in candidates
        ]
    )

    headings = normalize_headings(raw)

    if not headings:
        repo.store_section_tree(document_id, [])
        return

    title = _detect_title(headings)

    structural = []
    for h in headings:
        if h is title:
            continue

        idx = _safe_int(h.get("block_index"))
        zone = zone_map.get(idx, "body")

        # Front excludes only likely metadata leftovers.
        if zone == "front" and _is_front_meta_like(h):
            continue

        h2 = dict(h)
        h2["zone"] = zone
        structural.append(h2)

    structural = sorted(structural, key=lambda h: _safe_int(h.get("block_index")))

    if not structural:
        repo.store_section_tree(document_id, [])
        return

    body_headings = [
        h
        for h in structural
        if h.get("zone") == "body"
        and not _is_top_level_text(h.get("text"))
        and not _looks_like_terminal_major_heading(h)
    ]

    style_model = build_style_model(body_headings or structural)
    style_levels = style_model["levels"]

    rows = []
    stack = []
    node_id = 1

    for h in structural:
        zone = h.get("zone", "body")
        idx = _safe_int(h.get("block_index"))
        end = _safe_int(h.get("end_block_index"), idx)
        text = _norm(h.get("text")) or f"Section {node_id}"

        level = _final_level(h, zone, style_levels)

        # hard reset for back matter and explicit major-section transitions
        if zone == "back" or _is_top_level_text(text) or _looks_like_terminal_major_heading(h):
            stack = []
        else:
            while stack and _safe_int(stack[-1].get("level")) >= level:
                stack.pop()

        parent = stack[-1]["section_node_id"] if stack else None

        # root nodes must always be level 1
        if parent is None:
            level = 1

        node = {
            "section_node_id": node_id,
            "parent_section_node_id": parent,
            "heading_block_id": h.get("block_id"),
            "start_block_index": idx,
            "end_block_index": end,
            "page_start": h.get("page_index"),
            "page_end": h.get("page_index"),
            "level": level,
            "role": "heading",
            "title": text,
            "title_normalized": text.lower(),
            "is_numbered": False,
            "confidence": None,
            "source": f"section_tree_zoned_v3:{zone}",
        }

        rows.append(node)

        if zone != "back":
            stack.append(node)

        node_id += 1

    repo.store_section_tree(document_id, rows)
