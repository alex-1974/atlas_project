# src/atlas/document_understanding/layers/section_tree.py
from __future__ import annotations

from typing import Any

from atlas.document_understanding.core.heading_normalization import (
    is_appendix_heading,
    is_reference_heading,
    normalize_headings,
)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _estimate_body_font(blocks: list[dict[str, Any]]) -> float:
    sizes = [_safe_float(b.get("font_size")) for b in blocks if b.get("font_size") is not None]
    if not sizes:
        return 10.0
    sizes = sorted(sizes)
    return sizes[len(sizes) // 2]


def _is_typographic_heading(block: dict[str, Any], body_font: float) -> bool:
    size = _safe_float(block.get("font_size"))
    italic = bool(block.get("italic"))
    text = _norm(block.get("text"))

    if not text:
        return False

    if size >= body_font + 1.5:
        return True

    if italic and len(text.split()) <= 5 and size >= body_font - 0.2:
        return True

    return False


def _is_score_heading(block: dict[str, Any]) -> bool:
    heading = _safe_float(block.get("heading_score"))
    body = _safe_float(block.get("body_score"))
    noise = _safe_float(block.get("noise_score"))
    caption = _safe_float(block.get("caption_score"))
    reference = _safe_float(block.get("reference_score"))

    return (
        heading >= 0.35
        and heading > body
        and heading > noise
        and heading > caption
        and heading > reference
    )


def _collect_heading_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body_font = _estimate_body_font(blocks)
    candidates: list[dict[str, Any]] = []

    for block in blocks:
        text = _norm(block.get("text"))
        if not text:
            continue

        role = str(block.get("role") or "").lower()

        if role == "heading":
            candidates.append(block)
            continue

        if _is_score_heading(block):
            candidates.append(block)
            continue

        if _is_typographic_heading(block, body_font):
            candidates.append(block)
            continue

    return candidates


def _style_key(h: dict[str, Any]) -> tuple[float, bool]:
    return (
        round(_safe_float(h.get("font_size")), 1),
        bool(h.get("italic")),
    )


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    for row in rows:
        sig = (_safe_int(row.get("block_index"), -1), _norm(row.get("text")).lower())
        if sig in seen:
            continue
        seen.add(sig)
        out.append(row)

    return out


def _fetch_zone_map(repo, document_id: str) -> dict[Any, str]:
    if not hasattr(repo, "fetch_block_zones"):
        return {}

    try:
        rows = repo.fetch_block_zones(document_id) or []
    except Exception:
        return {}

    zone_map: dict[Any, str] = {}
    for row in rows:
        block_id = row.get("block_id")
        zone = row.get("zone")
        if block_id is not None and zone:
            zone_map[block_id] = str(zone)
    return zone_map


def _default_zone_for_heading(text: str) -> str:
    if is_reference_heading(text):
        return "back"
    if is_appendix_heading(text):
        return "back"
    return "body"


def _detect_title(headings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not headings:
        return None

    max_font = max(_safe_float(h.get("font_size")) for h in headings)
    candidates = [h for h in headings if _safe_float(h.get("font_size")) == max_font]
    candidates.sort(key=lambda h: _safe_int(h.get("block_index")))
    return candidates[0] if candidates else None


def _compute_style_stats(headings: list[dict[str, Any]]) -> dict[tuple[float, bool], dict[str, Any]]:
    buckets: dict[tuple[float, bool], list[dict[str, Any]]] = {}
    for h in headings:
        buckets.setdefault(_style_key(h), []).append(h)

    stats: dict[tuple[float, bool], dict[str, Any]] = {}
    for style, rows in buckets.items():
        indices = [_safe_int(r.get("block_index")) for r in rows]
        stats[style] = {
            "count": len(rows),
            "first_block_index": min(indices) if indices else 10**9,
            "font_size": style[0],
            "italic": style[1],
        }
    return stats


def _compute_style_levels(headings: list[dict[str, Any]]) -> dict[tuple[float, bool], int]:
    if not headings:
        return {}

    stats = _compute_style_stats(headings)

    ordered_styles = sorted(
        stats.keys(),
        key=lambda style: (
            -stats[style]["font_size"],   # larger first
            stats[style]["italic"],       # non-italic before italic
            stats[style]["first_block_index"],
            -stats[style]["count"],
        ),
    )

    return {style: idx + 1 for idx, style in enumerate(ordered_styles)}


def _final_level_for_heading(
    heading: dict[str, Any],
    zone: str,
    style_levels: dict[tuple[float, bool], int],
) -> int:
    text = _norm(heading.get("text"))

    if zone == "back":
        return 1

    if is_reference_heading(text) or is_appendix_heading(text):
        return 1

    return style_levels.get(_style_key(heading), 1)


def _sort_structural_headings(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        headings,
        key=lambda h: (
            _safe_int(h.get("block_index")),
            _safe_int(h.get("page_index")),
            _norm(h.get("text")).lower(),
        ),
    )


def compute_section_tree(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)
    zone_map = _fetch_zone_map(repo, document_id)

    candidates = _collect_heading_candidates(blocks)

    raw_headings = _dedupe(
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
                "noise_score": b.get("noise_score"),
                "caption_score": b.get("caption_score"),
                "reference_score": b.get("reference_score"),
            }
            for b in candidates
        ]
    )

    print("\n--- RAW CANDIDATES ---")
    for h in raw_headings:
        print(h)

    headings = normalize_headings(raw_headings)

    print("\n--- NORMALIZED HEADINGS ---")
    for h in headings:
        print(h)

    if not headings:
        repo.store_section_tree(document_id, [])
        return

    title = _detect_title(headings)

    structural_headings: list[dict[str, Any]] = []
    for h in headings:
        if h is title:
            continue

        text = _norm(h.get("text"))
        zone = zone_map.get(h.get("block_id")) or _default_zone_for_heading(text)

        # Front matter never becomes section tree content.
        if zone == "front":
            continue

        h2 = dict(h)
        h2["zone"] = zone
        structural_headings.append(h2)

    structural_headings = _sort_structural_headings(structural_headings)

    if not structural_headings:
        repo.store_section_tree(document_id, [])
        return

    body_headings = [h for h in structural_headings if h.get("zone") == "body"]
    style_levels = _compute_style_levels(body_headings or structural_headings)

    rows: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    node_id = 1

    for i, h in enumerate(structural_headings):
        text = _norm(h.get("text"))
        zone = h.get("zone") or "body"

        level = _final_level_for_heading(h, zone, style_levels)

        block_index = _safe_int(h.get("block_index"))
        end_block = _safe_int(h.get("end_block_index"), block_index)
        title_text = text or f"Section {i + 1}"

        while stack and _safe_int(stack[-1].get("level")) >= level:
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
            "source": f"section_tree_v2:{zone}",
        }

        rows.append(node)
        stack.append(node)
        node_id += 1

    repo.store_section_tree(document_id, rows)
