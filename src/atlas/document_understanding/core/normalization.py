# src/atlas/document_understanding/core/normalization.py
from __future__ import annotations

from statistics import median

from atlas.document_understanding.core.coordinate_system import DocumentCoordinateSystem


def _median_or_none(values: list[float | int | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return float(median(clean))


def estimate_document_coordinate_system(blocks: list[dict]) -> DocumentCoordinateSystem:
    """
    Estimate stable document-wide normalization references from working blocks.

    This is transitional:
    later this should be computed from lower-level layout atoms rather than blocks.
    """
    if not blocks:
        return DocumentCoordinateSystem(
            page_width=None,
            page_height=None,
            document_height=None,
            body_font_size=None,
            median_line_gap=None,
            median_paragraph_gap=None,
            default_column_left=None,
            default_column_right=None,
            column_count=None,
        )

    page_width = _median_or_none([b.get("page_width") for b in blocks])
    page_height = _median_or_none([b.get("page_height") for b in blocks])

    doc_y1_values = [b.get("doc_y1") for b in blocks if b.get("doc_y1") is not None]
    document_height = max(doc_y1_values) if doc_y1_values else None

    font_sizes = [b.get("font_size") for b in blocks]
    body_font_size = _median_or_none(font_sizes)

    whitespace_before = [
        b.get("whitespace_before")
        for b in blocks
        if b.get("whitespace_before") is not None and float(b.get("whitespace_before")) > 0.0
    ]
    median_line_gap = _median_or_none(whitespace_before)

    paragraph_like_gaps = [
        float(g)
        for g in whitespace_before
        if median_line_gap is not None and float(g) > median_line_gap * 1.35
    ]
    median_paragraph_gap = _median_or_none(paragraph_like_gaps) or median_line_gap

    x0_values = [b.get("x0") for b in blocks if b.get("x0") is not None]
    x1_values = [b.get("x1") for b in blocks if b.get("x1") is not None]

    default_column_left = _median_or_none(x0_values)
    default_column_right = _median_or_none(x1_values)

    return DocumentCoordinateSystem(
        page_width=page_width,
        page_height=page_height,
        document_height=document_height,
        body_font_size=body_font_size,
        median_line_gap=median_line_gap,
        median_paragraph_gap=median_paragraph_gap,
        default_column_left=default_column_left,
        default_column_right=default_column_right,
        column_count=1,
    )
