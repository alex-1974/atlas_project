"""
atlas.parse.typography

Bestimmt das Fließtextprofil eines Dokuments statistisch.

Ansatz:
- Profilseiten = mittleres Dokumentdrittel (aus page_format_profile)
- Blöcke innerhalb der Body-Region, Furniture ausgeklammert
- Filter: Blöcke mit ≥ 3 Zeilen UND ≥ 60% Spaltenbreite → Fließtext-Kandidaten
- Span-Ebene: font_size, font_name, bold, italic, color
- Median-Statistik → stabiles Fließtextprofil als Referenzpunkt
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf as fitz

from ._utils import (
    _clamp,
    _mad,
    _median,
    _middle_page_indexes,
    _percentile,
)
from .logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SpanStats:
    """Rohe Span-Messungen für einen einzelnen Textspan."""
    size: float
    font: str
    bold: bool
    italic: bool
    color: int        # RGB als integer (0xRRGGBB)
    char_count: int


@dataclass(slots=True)
class BodyTextProfile:
    """
    Statistisches Profil des dominanten Fließtexts.

    Alle Werte sind Mediane über Fließtext-Kandidaten im mittleren
    Dokumentdrittel — robust gegen Ausreißer und Sonderelemente.
    """

    # Schriftgröße
    dominant_size: float
    size_mad: float               # MAD als Stabilitätsmaß
    size_p10: float               # 10. Perzentil (untere Grenze)
    size_p90: float               # 90. Perzentil (obere Grenze)

    # Font
    dominant_font: str            # häufigster Font-Name
    dominant_font_family: str     # normalisierte Familie (vor erstem '+' oder '-')
    has_secondary_font: bool      # zweite Font-Familie vorhanden?
    secondary_font_family: str | None

    # Auszeichnungen
    body_bold_ratio: float        # Anteil bold-Spans im Fließtext (typisch ~0)
    body_italic_ratio: float      # Anteil italic-Spans

    # Farbe
    dominant_color: int           # typische Textfarbe (meist 0 = schwarz)
    is_colored_text: bool         # True wenn dominant_color nicht schwarz/dunkelgrau

    # Zeilenabstand
    dominant_line_height: float   # Median Zeilenabstand (y0[n+1] - y0[n])
    line_height_mad: float

    # Qualität
    sample_span_count: int        # Anzahl Spans die ins Profil eingingen
    sample_block_count: int       # Anzahl Fließtext-Kandidaten
    profile_page_count: int       # Anzahl Profilseiten

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _normalize_font_family(font_name: str) -> str:
    """
    Extrahiert die Font-Familie aus einem vollständigen Font-Namen.

    PyMuPDF liefert Namen wie 'ABCDEF+TimesNewRoman-Bold' oder
    'Helvetica-BoldOblique'. Wir wollen 'TimesNewRoman' bzw. 'Helvetica'.
    """
    name = font_name
    # Subset-Präfix entfernen (6 Großbuchstaben + '+')
    if len(name) > 7 and name[6] == '+' and name[:6].isupper():
        name = name[7:]
    # Stil-Suffix entfernen (-Bold, -Italic, -BoldOblique, etc.)
    for suffix in ('-Bold', '-Italic', '-BoldItalic', '-Oblique',
                   '-BoldOblique', '-Regular', '-Medium', '-Light',
                   ',Bold', ',Italic'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name


def _parse_flags(flags: int) -> tuple[bool, bool]:
    """Extrahiert bold und italic aus PyMuPDF span flags."""
    # flags bit 4 = superscript, bit 1 = italic, bit 4 = bold (varies)
    # PyMuPDF: flags & 1 = superscript, flags & 2 = italic,
    #          flags & 4 = serifed, flags & 8 = monospaced, flags & 16 = bold
    italic = bool(flags & 2)
    bold = bool(flags & 16)
    return bold, italic


def _most_common(values: list) -> object:
    """Gibt den häufigsten Wert zurück."""
    if not values:
        return None
    counts: dict = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _is_body_candidate(
    block: dict,
    body_x0: float,
    body_x1: float,
    col_width: float,
    min_line_count: int = 3,
    min_width_ratio: float = 0.55,
) -> bool:
    """
    Prüft ob ein Block ein Fließtext-Kandidat ist.

    Kriterien:
    - Mindestens min_line_count Zeilen
    - Blockbreite ≥ min_width_ratio × Spaltenbreite
    - Liegt innerhalb der Body-Region (x-Achse)
    """
    if block.get("type") != 0:
        return False
    lines = block.get("lines", [])
    if len(lines) < min_line_count:
        return False
    bbox = block["bbox"]
    block_width = bbox[2] - bbox[0]
    if col_width > 0 and block_width < col_width * min_width_ratio:
        return False
    # Muss horizontal im Body liegen
    if bbox[0] < body_x0 - 5.0 or bbox[2] > body_x1 + 5.0:
        return False
    return True


def _span_text(span: dict) -> str:
    """
    Extrahiert Text aus einem Span.

    rawdict liefert bei manchen PDFs span["text"] als leeren String —
    der Text steckt dann in span["chars"][n]["c"].
    """
    text = span.get("text", "")
    if text:
        return text
    # Fallback: aus chars rekonstruieren
    chars = span.get("chars", [])
    if chars:
        return "".join(c.get("c", "") for c in chars)
    return ""


def _extract_spans_from_block(block: dict) -> list[SpanStats]:
    """Extrahiert SpanStats aus einem rawdict-Block."""
    spans = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text = _span_text(span).strip()
            if not text or len(text) < 2:
                continue
            size = float(span.get("size", 0.0))
            if size <= 0:
                continue
            bold, italic = _parse_flags(span.get("flags", 0))
            spans.append(SpanStats(
                size=round(size * 2) / 2,  # auf 0.5pt runden
                font=span.get("font", ""),
                bold=bold,
                italic=italic,
                color=int(span.get("color", 0)),
                char_count=len(text),
            ))
    return spans


def _extract_line_heights_from_block(block: dict) -> list[float]:
    """
    Berechnet Zeilenabstände (y0[n+1] - y0[n]) innerhalb eines Blocks.

    Nur positive Abstände die plausibel sind (< 3× Schriftgröße).
    """
    line_y0s = []
    for line in block.get("lines", []):
        bbox = line.get("bbox")
        if bbox:
            line_y0s.append(float(bbox[1]))

    if len(line_y0s) < 2:
        return []

    heights = []
    for i in range(1, len(line_y0s)):
        h = line_y0s[i] - line_y0s[i - 1]
        if 4.0 < h < 50.0:  # plausible Zeilenabstände
            heights.append(h)
    return heights


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------


def extract_body_text_profile(
    pdf_path: Path,
    body_x0: float,
    body_y0: float,
    body_x1: float,
    body_y1: float,
    col_width: float,
    header_y1: float | None,
    footer_y0: float | None,
    profile_page_indexes: list[int] | None = None,
    page_count: int | None = None,
) -> BodyTextProfile | None:
    """
    Bestimmt das Fließtextprofil eines Dokuments.

    Misst auf Span-Ebene über Fließtext-Kandidaten im mittleren
    Dokumentbereich. Gibt None zurück wenn zu wenige Samples gefunden werden.

    Parameter:
        pdf_path            Pfad zum PDF
        body_x0/y0/x1/y1   Body-Region aus DocumentGeometryProfile
        col_width           Spaltenbreite aus VerticalProfile (0 = unbekannt)
        header_y1           Unterkante des Headers (None = kein Header)
        footer_y0           Oberkante des Footers (None = kein Footer)
        profile_page_indexes  Seiten für Profilierung (None = mittleres Drittel)
        page_count          Gesamtseitenanzahl (nur für Fallback nötig)
    """
    all_spans: list[SpanStats] = []
    all_line_heights: list[float] = []
    sample_block_count = 0
    profile_pages_used = 0

    # Effektive Spaltenbreite: falls unbekannt, Body-Breite nehmen
    effective_col_width = col_width if col_width > 10.0 else (body_x1 - body_x0)

    with fitz.open(pdf_path) as doc:
        total_pages = len(doc)

        # Profilseiten bestimmen
        if profile_page_indexes is None:
            profile_page_indexes = _middle_page_indexes(
                page_count if page_count is not None else total_pages
            )

        for page_idx in profile_page_indexes:
            if page_idx >= total_pages:
                continue

            page = doc.load_page(page_idx)
            raw = page.get_text(
                "rawdict",
                flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
            )

            for block in raw.get("blocks", []):
                bbox = block.get("bbox", (0, 0, 0, 0))
                b_y0, b_y1 = float(bbox[1]), float(bbox[3])

                # Header ausschließen
                if header_y1 is not None and b_y0 < header_y1 + 2.0:
                    continue

                # Footer ausschließen
                if footer_y0 is not None and b_y1 > footer_y0 - 2.0:
                    continue

                # Body-Region vertikal: nur untere Grenze hart,
                # obere Grenze nur wenn Header vorhanden.
                # body_y0 kann konservativ sein wenn kein Header.
                if header_y1 is None and b_y0 < 0.0:
                    continue
                if b_y1 > body_y1 + 5.0:
                    continue

                if not _is_body_candidate(
                    block, body_x0, body_x1, effective_col_width
                ):
                    continue

                spans = _extract_spans_from_block(block)
                if not spans:
                    continue

                all_spans.extend(spans)
                all_line_heights.extend(_extract_line_heights_from_block(block))
                sample_block_count += 1

            profile_pages_used += 1

    if len(all_spans) < 20:
        logger.warning(
            "typography: zu wenige Spans (%d) für stabiles Profil in %s",
            len(all_spans), pdf_path.name,
        )
        return None

    # --- Schriftgröße ---
    sizes = [s.size for s in all_spans]
    dominant_size = _median(sizes)
    size_mad = _mad(sizes, dominant_size)
    size_p10 = _percentile(sizes, 0.10)
    size_p90 = _percentile(sizes, 0.90)

    # --- Font ---
    fonts = [s.font for s in all_spans if s.font]
    dominant_font = _most_common(fonts) or ""
    families = [_normalize_font_family(f) for f in fonts if f]
    dominant_family = _most_common(families) or ""

    # Zweite Font-Familie: häufigste die nicht die dominante ist
    family_counts: dict[str, int] = {}
    for fam in families:
        family_counts[fam] = family_counts.get(fam, 0) + 1
    secondary_family = None
    has_secondary = False
    if len(family_counts) > 1:
        sorted_fams = sorted(family_counts.items(), key=lambda kv: -kv[1])
        for fam, count in sorted_fams[1:]:
            # Nur als sekundär zählen wenn mind. 10% der Spans
            if count >= len(families) * 0.10:
                secondary_family = fam
                has_secondary = True
                break

    # --- Auszeichnungen ---
    total = len(all_spans)
    bold_count = sum(1 for s in all_spans if s.bold)
    italic_count = sum(1 for s in all_spans if s.italic)
    body_bold_ratio = bold_count / max(1, total)
    body_italic_ratio = italic_count / max(1, total)

    # --- Farbe ---
    colors = [s.color for s in all_spans]
    dominant_color = _most_common(colors) or 0
    # Schwarz/Dunkelgrau: alle drei RGB-Kanäle < 80
    r = (dominant_color >> 16) & 0xFF
    g = (dominant_color >> 8) & 0xFF
    b = dominant_color & 0xFF
    is_colored = not (r < 80 and g < 80 and b < 80)

    # --- Zeilenabstand ---
    if all_line_heights:
        dominant_line_height = _median(all_line_heights)
        line_height_mad = _mad(all_line_heights, dominant_line_height)
    else:
        # Fallback: 1.2× Schriftgröße
        dominant_line_height = dominant_size * 1.2
        line_height_mad = 0.0

    logger.debug(
        "typography: size=%.1f±%.1f font=%s bold=%.0f%% spans=%d blocks=%d pages=%d",
        dominant_size, size_mad, dominant_family,
        body_bold_ratio * 100, total, sample_block_count, profile_pages_used,
    )

    return BodyTextProfile(
        dominant_size=dominant_size,
        size_mad=size_mad,
        size_p10=size_p10,
        size_p90=size_p90,
        dominant_font=dominant_font,
        dominant_font_family=dominant_family,
        has_secondary_font=has_secondary,
        secondary_font_family=secondary_family,
        body_bold_ratio=round(body_bold_ratio, 3),
        body_italic_ratio=round(body_italic_ratio, 3),
        dominant_color=dominant_color,
        is_colored_text=is_colored,
        dominant_line_height=round(dominant_line_height, 2),
        line_height_mad=round(line_height_mad, 2),
        sample_span_count=total,
        sample_block_count=sample_block_count,
        profile_page_count=profile_pages_used,
    )
