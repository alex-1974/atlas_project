"""
atlas.parse._utils

Geteilte Hilfsfunktionen für zones.py und vertical.py.

Alle Funktionen sind dokumentintern und nicht Teil der öffentlichen API.
"""

from __future__ import annotations

from statistics import median


# ---------------------------------------------------------------------------
# Statistische Hilfsfunktionen
# ---------------------------------------------------------------------------


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _mad(values: list[float], med: float | None = None) -> float:
    """Median Absolute Deviation."""
    if not values:
        return 0.0
    m = med if med is not None else _median(values)
    return _median([abs(v - m) for v in values])


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _mad_tolerance(
    values: list[float],
    reference_width: float,
    factor: float = 2.0,
    floor_ratio: float = 0.005,
) -> float:
    """
    MAD-basierte Kohärenz-Schwelle.

    Minimum: reference_width × floor_ratio — verhindert Kollaps bei
    sehr stabilen Verteilungen (MAD ≈ 0).
    """
    if not values:
        return reference_width * floor_ratio
    med = _median(values)
    mad = _mad(values, med)
    return max(mad * factor, reference_width * floor_ratio)


# ---------------------------------------------------------------------------
# Block- und Seiten-Utilities
# ---------------------------------------------------------------------------


def _is_text_like(block: object) -> bool:
    return (
        getattr(block, "block_type", None) == 0
        and bool(str(getattr(block, "text", "")).strip())
    )


def _is_odd_page(page_index: int) -> bool:
    return (page_index + 1) % 2 == 1


def _middle_page_indexes(page_count: int) -> list[int]:
    """Mittleres Drittel des Dokuments als Profilseiten."""
    if page_count <= 6:
        return list(range(page_count))
    start = max(0, page_count // 3)
    end = min(page_count, (2 * page_count) // 3)
    if end <= start:
        return list(range(page_count))
    return list(range(start, end))


def _rect_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)
