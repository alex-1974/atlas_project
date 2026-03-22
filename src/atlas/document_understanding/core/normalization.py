# src/atlas/document_understanding/core/normalization.py
from __future__ import annotations

from statistics import median

from atlas.document_understanding.core.coordinate_system import DocumentCoordinateSystem


def _median_or_none(values: list[float | int | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return float(median(clean))


def _quantile_or_none(values: list[float | int | None], q: float) -> float | None:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return float(clean[0])

    q = max(0.0, min(1.0, float(q)))
    pos = q * (len(clean) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(clean) - 1)
    frac = pos - lo
    return float(clean[lo] * (1.0 - frac) + clean[hi] * frac)


def estimate_document_coordinate_system(blocks: list[dict]) -> DocumentCoordinateSystem:
    """
    Estimate stable document-wide normalization references from working blocks.

    Transitional implementation:
    later this should be computed from lower-level layout atoms rather than blocks.
    """
    if not blocks:
        return DocumentCoordinateSystem(
            page_width=None,
            page_height=None,
            document_height=None,
            body_font_size=None,
            font_size_q25=None,
            font_size_q75=None,
            font_size_q90=None,
            median_line_gap=None,
            median_paragraph_gap=None,
            gap_ratio=None,
            default_column_left=None,
            default_column_right=None,
            column_count=None,
        )

    page_width = _median_or_none([b.get("page_width") for b in blocks])
    page_height = _median_or_none([b.get("page_height") for b in blocks])

    doc_y1_values = [b.get("doc_y1") for b in blocks if b.get("doc_y1") is not None]
    document_height = max(doc_y1_values) if doc_y1_values else None

    font_sizes = [b.get("font_size") for b in blocks if b.get("font_size") is not None]
    body_font_size = _median_or_none(font_sizes)
    font_size_q25 = _quantile_or_none(font_sizes, 0.25)
    font_size_q75 = _quantile_or_none(font_sizes, 0.75)
    font_size_q90 = _quantile_or_none(font_sizes, 0.90)

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

    gap_ratio = None
    if (
        median_paragraph_gap is not None
        and median_line_gap is not None
        and median_line_gap != 0
    ):
        gap_ratio = float(median_paragraph_gap) / float(median_line_gap)

    x0_values = [b.get("x0") for b in blocks if b.get("x0") is not None]
    x1_values = [b.get("x1") for b in blocks if b.get("x1") is not None]

    default_column_left = _median_or_none(x0_values)
    default_column_right = _median_or_none(x1_values)

    return DocumentCoordinateSystem(
        page_width=page_width,
        page_height=page_height,
        document_height=document_height,
        body_font_size=body_font_size,
        font_size_q25=font_size_q25,
        font_size_q75=font_size_q75,
        font_size_q90=font_size_q90,
        median_line_gap=median_line_gap,
        median_paragraph_gap=median_paragraph_gap,
        gap_ratio=gap_ratio,
        default_column_left=default_column_left,
        default_column_right=default_column_right,
        column_count=1,
    )
