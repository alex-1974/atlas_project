from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Sequence


@dataclass(slots=True, frozen=True)
class DocumentCoordinateSystem:
    page_width: float | None
    page_height: float | None
    document_height: float | None

    body_font_size: float | None
    font_size_q25: float | None
    font_size_q75: float | None
    font_size_q90: float | None

    median_line_gap: float | None
    median_paragraph_gap: float | None
    gap_ratio: float | None

    default_column_left: float | None
    default_column_right: float | None
    column_count: int | None


def safe_ratio(value: float | None, denom: float | None) -> float | None:
    if value is None or denom is None or denom == 0:
        return None
    return float(value) / float(denom)


def _clean_floats(values: Iterable[float | int | None]) -> list[float]:
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            out.append(f)
    return out


def _quantile(sorted_values: Sequence[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    q = max(0.0, min(1.0, float(q)))
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def _get_first_number(block: dict, *keys: str) -> float | None:
    for key in keys:
        value = block.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _looks_body_like(block: dict) -> bool:
    role = str(block.get("role") or "").lower()
    text = str(block.get("text") or "").strip()

    if role == "body":
        return True

    # fallback: long-ish text blocks are usually body-like
    word_count = len(text.split())
    char_count = len(text)
    return word_count >= 12 or char_count >= 80


def derive_document_coordinate_system(blocks: list[dict]) -> DocumentCoordinateSystem:
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

    page_widths = _clean_floats(
        _get_first_number(b, "page_width") for b in blocks
    )
    page_heights = _clean_floats(
        _get_first_number(b, "page_height") for b in blocks
    )
    doc_heights = _clean_floats(
        _get_first_number(b, "document_height") for b in blocks
    )

    all_font_sizes = _clean_floats(
        _get_first_number(b, "font_size", "size", "dominant_font_size") for b in blocks
    )
    body_font_sizes = _clean_floats(
        _get_first_number(b, "font_size", "size", "dominant_font_size")
        for b in blocks
        if _looks_body_like(b)
    )

    font_sizes_sorted = sorted(all_font_sizes)
    body_font_size = (
        float(median(body_font_sizes))
        if body_font_sizes
        else (float(median(all_font_sizes)) if all_font_sizes else None)
    )

    line_gaps = _clean_floats(
        _get_first_number(b, "gap_before", "line_gap_before", "spacing_before")
        for b in blocks
    )
    paragraph_gaps = _clean_floats(
        _get_first_number(b, "paragraph_gap_before", "para_gap_before", "gap_after_paragraph")
        for b in blocks
    )

    median_line_gap = float(median(line_gaps)) if line_gaps else None
    median_paragraph_gap = float(median(paragraph_gaps)) if paragraph_gaps else None
    gap_ratio = safe_ratio(median_paragraph_gap, median_line_gap)

    lefts = _clean_floats(_get_first_number(b, "x0", "left") for b in blocks)
    rights = _clean_floats(_get_first_number(b, "x1", "right") for b in blocks)

    page_indices = {
        int(v)
        for v in (
            _get_first_number(b, "page_index", "page_num", "page")
            for b in blocks
        )
        if v is not None
    }

    column_values = {
        int(v)
        for v in (
            _get_first_number(b, "column_id", "column", "col")
            for b in blocks
        )
        if v is not None
    }
    column_count = len(column_values) if column_values else None

    return DocumentCoordinateSystem(
        page_width=float(median(page_widths)) if page_widths else None,
        page_height=float(median(page_heights)) if page_heights else None,
        document_height=max(doc_heights) if doc_heights else None,
        body_font_size=body_font_size,
        font_size_q25=_quantile(font_sizes_sorted, 0.25),
        font_size_q75=_quantile(font_sizes_sorted, 0.75),
        font_size_q90=_quantile(font_sizes_sorted, 0.90),
        median_line_gap=median_line_gap,
        median_paragraph_gap=median_paragraph_gap,
        gap_ratio=gap_ratio,
        default_column_left=float(median(lefts)) if lefts else None,
        default_column_right=float(median(rights)) if rights else None,
        column_count=column_count or (1 if page_indices else None),
    )
