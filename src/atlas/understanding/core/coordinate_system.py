# src/atlas/understanding/core/coordinate_system.py
from __future__ import annotations

"""Dokumentweites Koordinatensystem für die DU-Pipeline.

Einzige Implementierung: derive_document_coordinate_system().
Die veraltete estimate_document_coordinate_system() aus normalization.py
wird nicht portiert (Bug 4 Fix — zwei parallele Implementierungen).
"""

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Sequence


@dataclass(slots=True, frozen=True)
class DocumentCoordinateSystem:
    """Dokumentweite Normalisierungsreferenzen.

    Wird einmal pro Dokument berechnet und an alle Schicht-1-Module
    weitergegeben. Unveränderlich nach der Berechnung.
    """
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


# ── Interne Hilfsfunktionen ───────────────────────────────────────────────────

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


def _first_number(block: dict, *keys: str) -> float | None:
    for key in keys:
        v = block.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _is_body_like(block: dict) -> bool:
    """Heuristik: ist dieser Block wahrscheinlich Fließtext?

    Wird ausschließlich zur Bestimmung der Body-Font-Größe verwendet.
    Kein Rollenwissen — nur Textlänge.
    """
    text = str(block.get("text") or "").strip()
    return len(text.split()) >= 12 or len(text) >= 80


# ── Öffentliche API ───────────────────────────────────────────────────────────

def derive_document_coordinate_system(
    blocks: list[dict],
) -> DocumentCoordinateSystem:
    """Berechnet dokumentweite Normalisierungsreferenzen aus Rohblöcken.

    Erwartet eine Liste von Dicts mit den Feldern aus du_blocks und
    du_pages (page_width, page_height, font_size, x0, x1, ...).

    Gibt ein leeres Koordinatensystem zurück wenn keine Blöcke vorhanden.
    """
    if not blocks:
        return DocumentCoordinateSystem(
            page_width=None, page_height=None, document_height=None,
            body_font_size=None, font_size_q25=None,
            font_size_q75=None, font_size_q90=None,
            median_line_gap=None, median_paragraph_gap=None,
            gap_ratio=None, default_column_left=None,
            default_column_right=None, column_count=None,
        )

    page_widths  = _clean_floats(_first_number(b, "page_width")  for b in blocks)
    page_heights = _clean_floats(_first_number(b, "page_height") for b in blocks)
    doc_heights  = _clean_floats(_first_number(b, "doc_y1")      for b in blocks)

    all_font_sizes  = _clean_floats(
        _first_number(b, "font_size") for b in blocks
    )
    body_font_sizes = _clean_floats(
        _first_number(b, "font_size")
        for b in blocks if _is_body_like(b)
    )

    font_sizes_sorted = sorted(all_font_sizes)
    body_font_size = (
        float(median(body_font_sizes)) if body_font_sizes
        else (float(median(all_font_sizes)) if all_font_sizes else None)
    )

    line_gaps = _clean_floats(
        _first_number(b, "whitespace_before") for b in blocks
    )
    median_line_gap = float(median(line_gaps)) if line_gaps else None

    para_gaps = (
        [g for g in line_gaps if median_line_gap and g > median_line_gap * 1.35]
        if median_line_gap else []
    )
    median_paragraph_gap = (
        float(median(para_gaps)) if para_gaps else median_line_gap
    )

    gap_ratio = (
        median_paragraph_gap / median_line_gap
        if median_paragraph_gap and median_line_gap
        else None
    )

    lefts  = _clean_floats(_first_number(b, "x0") for b in blocks)
    rights = _clean_floats(_first_number(b, "x1") for b in blocks)

    return DocumentCoordinateSystem(
        page_width=float(median(page_widths))   if page_widths   else None,
        page_height=float(median(page_heights)) if page_heights  else None,
        document_height=max(doc_heights)        if doc_heights   else None,
        body_font_size=body_font_size,
        font_size_q25=_quantile(font_sizes_sorted, 0.25),
        font_size_q75=_quantile(font_sizes_sorted, 0.75),
        font_size_q90=_quantile(font_sizes_sorted, 0.90),
        median_line_gap=median_line_gap,
        median_paragraph_gap=median_paragraph_gap,
        gap_ratio=gap_ratio,
        default_column_left=float(median(lefts))   if lefts   else None,
        default_column_right=float(median(rights)) if rights  else None,
        column_count=1,
    )
