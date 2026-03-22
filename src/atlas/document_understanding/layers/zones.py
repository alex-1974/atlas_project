# src/atlas/document_understanding/layers/zones.py
from __future__ import annotations

from typing import Any


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _is_references(text: str) -> bool:
    return text in {"references", "bibliography", "works cited", "literature cited"}


def _is_appendix(text: str) -> bool:
    return text == "appendix" or text.startswith("appendix ")


def _detect_boundaries(blocks: list[dict[str, Any]]) -> dict[str, int | None]:
    first_heading = None
    references_start = None
    appendix_start = None

    for b in blocks:
        role = (b.get("role") or "").lower()
        text = _norm(b.get("text"))
        idx = _safe_int(b.get("block_index"))

        if role == "heading" and first_heading is None:
            first_heading = idx

        if _is_references(text) and references_start is None:
            references_start = idx

        if _is_appendix(text) and appendix_start is None:
            appendix_start = idx

    return {
        "first_heading": first_heading,
        "references_start": references_start,
        "appendix_start": appendix_start,
    }


def _assign_zone(block: dict[str, Any], boundaries: dict[str, int | None]) -> str:
    idx = _safe_int(block.get("block_index"))

    ref = boundaries["references_start"]
    app = boundaries["appendix_start"]
    first = boundaries["first_heading"]

    if ref is not None and idx >= ref:
        return "back"
    if app is not None and idx >= app:
        return "back"
    if first is not None and idx < first:
        return "front"
    return "body"


def compute_zones(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)
    if not blocks:
        return

    boundaries = _detect_boundaries(blocks)

    rows = []
    for b in blocks:
        zone = _assign_zone(b, boundaries)
        rows.append(
            {
                "block_id": b.get("block_id"),
                "zone": zone,
                "zone_confidence": 1.0,
            }
        )

    repo.store_block_zones(document_id, rows)
