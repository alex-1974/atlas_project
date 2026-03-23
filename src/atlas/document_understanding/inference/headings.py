from __future__ import annotations

from typing import Any


# ------------------------------------------------------------
# utils
# ------------------------------------------------------------

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


def _safe_bool(v: Any) -> bool:
    return bool(v)


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


# ------------------------------------------------------------
# zones
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# style / document model
# ------------------------------------------------------------

def _style_key(block: dict[str, Any]) -> tuple[str, float, bool]:
    return (
        str(block.get("font_family") or ""),
        round(_safe_float(block.get("font_size")), 1),
        _safe_bool(block.get("italic")),
    )


def _estimate_body_style(blocks: list[dict[str, Any]]) -> tuple[str | None, float | None]:
    counts: dict[tuple[str, float], int] = {}

    for b in blocks:
        role = str(b.get("role") or "")
        body_score = _safe_float(b.get("body_score"))
        word_count = _safe_int(b.get("word_count"))
        if role == "body" or (body_score >= 0.5 and word_count >= 8):
            key = (
                str(b.get("font_family") or "") or None,
                round(_safe_float(b.get("font_size")), 1),
            )
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return None, None

    best = max(counts.items(), key=lambda kv: kv[1])[0]
    return best[0], best[1]


def _build_document_model(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    body_font_family, body_font_size = _estimate_body_style(blocks)

    style_clusters: dict[str, dict[str, Any]] = {}
    for b in blocks:
        key = _style_key(b)
        skey = f"{key[0]}|{key[1]}|{int(key[2])}"
        style_clusters.setdefault(
            skey,
            {
                "font_family": key[0],
                "font_size": key[1],
                "italic": key[2],
                "count": 0,
            },
        )
        style_clusters[skey]["count"] += 1

    return {
        "body_font_family": body_font_family,
        "body_font_size": body_font_size,
        "style_clusters": style_clusters,
        "heading_style_candidates": [],
    }


# ------------------------------------------------------------
# zone-aware score adjustment
# ------------------------------------------------------------

def _adjust_heading_score(block: dict[str, Any], zone: str) -> float:
    h = _safe_float(block.get("heading_score"))
    b = _safe_float(block.get("body_score"))
    n = _safe_float(block.get("noise_score"))
    c = _safe_float(block.get("caption_score"))
    r = _safe_float(block.get("reference_score"))

    text = _norm(block.get("text"))
    font_size = _safe_float(block.get("font_size"))
    italic = _safe_bool(block.get("italic"))
    title_score = _safe_float(block.get("title_score"))
    word_count = _safe_int(block.get("word_count"))
    is_references_marker = _safe_bool(block.get("is_references_marker"))
    is_appendix_marker = _safe_bool(block.get("is_appendix_marker"))
    is_figure_marker = _safe_bool(block.get("is_figure_marker"))
    is_table_marker = _safe_bool(block.get("is_table_marker"))
    contains_doi = _safe_bool(block.get("contains_doi"))
    contains_email = _safe_bool(block.get("contains_email"))

    # Strong negative evidence first
    if is_figure_marker or is_table_marker:
        h *= 0.25
    if c >= 0.45:
        h *= 0.35
    if n >= 0.45:
        h *= 0.50
    if contains_doi or contains_email:
        h *= 0.50

    if zone == "front":
        # suppress title/meta bleed, but do not annihilate short early section heads
        if title_score >= 0.5 and font_size >= 14.0:
            h *= 0.25
        elif word_count >= 8:
            h *= 0.65
        else:
            h *= 0.85

    elif zone == "body":
        if h > b:
            h *= 1.05
        if italic and 1 <= word_count <= 6:
            h *= 1.05

    elif zone == "back":
        # promote structural anchors, only mildly damp other late junk
        if is_references_marker or is_appendix_marker or any(
            k in text for k in ("reference", "bibliograph", "appendix", "acknowledg", "conclusion")
        ):
            h = max(h, 0.75)
        elif r >= 0.35:
            h *= 0.90
        else:
            h *= 0.80

    return max(0.0, min(1.0, h))


def _is_title_candidate(block: dict[str, Any], zone: str) -> bool:
    if zone != "front":
        return False
    font_size = _safe_float(block.get("font_size"))
    title_score = _safe_float(block.get("title_score"))
    heading_score = _safe_float(block.get("heading_score"))
    return font_size >= 14.0 and max(title_score, heading_score) >= 0.55


def _should_keep_heading(block: dict[str, Any], zone: str, adjusted_heading_score: float) -> bool:
    body_score = _safe_float(block.get("body_score"))
    noise_score = _safe_float(block.get("noise_score"))
    caption_score = _safe_float(block.get("caption_score"))
    word_count = _safe_int(block.get("word_count"))
    text = _norm(block.get("text"))

    if not text:
        return False

    if zone == "front":
        return adjusted_heading_score >= 0.55

    if zone == "body":
        return adjusted_heading_score >= max(0.42, body_score * 0.95) and caption_score < 0.5 and noise_score < 0.6

    if zone == "back":
        if any(k in text for k in ("reference", "bibliograph", "appendix", "acknowledg", "conclusion")):
            return True
        return adjusted_heading_score >= 0.48 and word_count <= 10

    return adjusted_heading_score >= 0.45


# ------------------------------------------------------------
# levels
# ------------------------------------------------------------

def _assign_levels(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Keep heading candidate levels shallow and deterministic.
    The real hierarchy is built later in section_tree.py.
    """
    out: list[dict[str, Any]] = []
    for c in candidates:
        c2 = dict(c)
        if c2.get("is_title"):
            c2["level"] = 0
        else:
            c2["level"] = 1
        out.append(c2)
    return out


# ------------------------------------------------------------
# main
# ------------------------------------------------------------

def compute_headings(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)
    zone_map = _fetch_zone_map(repo, document_id)

    model = _build_document_model(blocks)

    candidates: list[dict[str, Any]] = []

    for block in blocks:
        idx = _safe_int(block.get("block_index"))
        zone = zone_map.get(idx, "body")

        adjusted_heading_score = _adjust_heading_score(block, zone)

        if not _should_keep_heading(block, zone, adjusted_heading_score):
            continue

        candidate = {
            "block_id": block.get("block_id"),
            "heading_score": adjusted_heading_score,
            "level": 1,
            "is_title": _is_title_candidate(block, zone),
        }
        candidates.append(candidate)

    candidates = _assign_levels(candidates)

    repo.store_document_model(document_id, model)
    repo.store_heading_candidates(document_id, candidates)
