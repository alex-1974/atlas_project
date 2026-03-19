from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class DocumentCoordinateSystem:
    page_width: float | None
    page_height: float | None
    document_height: float | None
    body_font_size: float | None
    median_line_gap: float | None
    median_paragraph_gap: float | None
    default_column_left: float | None
    default_column_right: float | None
    column_count: int | None


def safe_ratio(value: float | None, denom: float | None) -> float | None:
    if value is None or denom is None or denom == 0:
        return None
    return float(value) / float(denom)
