"""
atlas.parse.document_zones

Bestimmt die drei Dokumentzonen: Frontmatter, Body, Backmatter.

Ansatz:
- Vorwärts durch die Seiten: Body-Beginn durch Markword-Anker
  und typografische Übereinstimmung mit dem Geometry-Profil
- Rückwärts durch die Seiten: Backmatter-Beginn durch Markword-Anker
- Konfidenz pro Grenze: wie stark war das Signal

Öffentliche API:
    zones = detect_document_zones(pdf_path, profile, observations, body_text_profile)
    zones.frontmatter_end   # letzte Frontmatter-Seite (0-basiert), None = keine
    zones.body_start        # erste Body-Seite (0-basiert)
    zones.backmatter_start  # erste Backmatter-Seite (0-basiert), None = keine
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf as fitz

from ._utils import _middle_page_indexes
from .logging import get_logger
from .section_labels import (
    ALL_BACK_MATTER_HEADINGS,
    ALL_BODY_START_HEADINGS,
    ALL_FRONTMATTER_HEADINGS,
    BODY_START_NUMBERED_RE,
    BODY_START_RE,
    BACKMATTER_RE,
    FRONTMATTER_RE,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ZoneBoundary:
    """Eine erkannte Zonengrenze mit Konfidenz und Begründung."""
    page_index: int          # 0-basiert
    confidence: float        # 0.0–1.0
    signal: str              # was hat ausgelöst: "numbered_heading", "markword", "typography", "fallback"
    text_snippet: str        # der Block-Text der das Signal ausgelöst hat


@dataclass(slots=True)
class DocumentZones:
    """
    Die drei Zonen eines Dokuments.

    Alle Seitenindizes sind 0-basiert.

    frontmatter: [0 .. body_start - 1]
    body:        [body_start .. backmatter_start - 1]  (oder bis Ende)
    backmatter:  [backmatter_start .. page_count - 1]  (oder leer)
    """
    page_count: int

    body_start: int                       # erste Body-Seite
    body_start_boundary: ZoneBoundary

    backmatter_start: int | None          # erste Backmatter-Seite, None = keine
    backmatter_boundary: ZoneBoundary | None

    @property
    def frontmatter_pages(self) -> list[int]:
        return list(range(0, self.body_start))

    @property
    def body_pages(self) -> list[int]:
        end = self.backmatter_start if self.backmatter_start is not None else self.page_count
        return list(range(self.body_start, end))

    @property
    def backmatter_pages(self) -> list[int]:
        if self.backmatter_start is None:
            return []
        return list(range(self.backmatter_start, self.page_count))

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase + whitespace-normalisiert."""
    return " ".join(text.lower().split())


def _blocks_on_page(page: fitz.Page) -> list[tuple[float, float, str]]:
    """
    Gibt (y0, block_width, text) für alle Textblöcke einer Seite zurück.
    Sortiert nach y0.
    """
    result = []
    for b in page.get_text("blocks"):
        if b[6] != 0:  # nur Textblöcke
            continue
        text = b[4].strip()
        if not text:
            continue
        y0 = float(b[1])
        width = float(b[2]) - float(b[0])
        result.append((y0, width, text))
    result.sort()
    return result


def _first_line(text: str) -> str:
    """Erste nicht-leere Zeile eines Blocks."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return text[:80].strip()


def _is_body_like_page(
    page_index: int,
    observations: list,
    body_text_profile,
) -> bool:
    """
    Heuristik: Ist diese Seite typografisch 'normal' (nicht Titelseite)?

    Eine Seite gilt als body-like wenn:
    - Das vertikale Profil passt (normale Spaltenanzahl)
    - Oder (für Seiten ohne vertikale Observation) wir auf Typography-Ebene
      sind (wird hier nicht genutzt, Fallback-Heuristik)
    """
    if page_index < len(observations):
        obs = observations[page_index]
        if obs.vertical is not None:
            # Seiten ohne erkannte Spalten sind meist Bild/Titel-Seiten
            return obs.vertical.observed_column_count > 0
    return True  # Fallback: annehmen dass normal


def _score_block_as_body_start(
    text: str,
    y0: float,
    page_height: float,
) -> tuple[float, str]:
    """
    Bewertet einen Block als potentiellen Body-Beginn.

    Gibt (score, signal_name) zurück.
    Score 1.0 = sehr sicherer Body-Beginn.
    Score 0.0 = kein Signal.
    """
    first = _first_line(text)
    norm = _normalize(first)

    # Stärkstes Signal: nummerierte Überschrift
    if BODY_START_NUMBERED_RE.match(first):
        # Zusatzcheck: Fußnoten-Blöcke haben viele kurze Zeilen mit Nummern.
        # Eine echte Kapitelüberschrift steht entweder allein (1 Zeile)
        # oder gefolgt von Fließtext (viele Zeilen). Fußnotenblöcke haben
        # typischerweise mehrere Zeilen aber JEDE beginnt mit einer Zahl.
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) > 1:
            # Wenn mehr als die Hälfte der Zeilen mit einer Zahl beginnt:
            # das ist eine Fußnotenliste, keine Überschrift
            num_start = sum(1 for l in lines if l and l[0].isdigit())
            if num_start / len(lines) >= 0.5:
                return 0.0, ""
        # Zusatzcheck: Literaturverweis-Fußnoten ("3 Margaret Wood, ...")
        # haben typischerweise 2 Zeilen, zweite Zeile enthält Jahreszahl oder "pp."
        if len(lines) <= 3:
            import re as _re
            rest = " ".join(lines[1:])
            if _re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b|\bpp\.\b|\bvol\.\b|\barch\.\b", rest, _re.IGNORECASE):
                return 0.0, ""
        return 1.0, "numbered_heading"

    # Starkes Signal: explizites Body-Markword
    if BODY_START_RE.match(first) and norm in ALL_BODY_START_HEADINGS:
        return 0.9, "markword_body_start"

    return 0.0, ""


def _is_backmatter_block(text: str) -> tuple[bool, str]:
    """Prüft ob ein Block ein Backmatter-Anker ist."""
    first = _first_line(text)
    norm = _normalize(first)
    if BACKMATTER_RE.match(first) and norm in ALL_BACK_MATTER_HEADINGS:
        return True, norm
    return False, ""


def _page_has_frontmatter_marker(blocks: list[tuple[float, float, str]]) -> bool:
    """True wenn die Seite einen Frontmatter-Marker enthält."""
    for _y0, _w, text in blocks:
        first = _first_line(text)
        norm = _normalize(first)
        if FRONTMATTER_RE.match(first) and norm in ALL_FRONTMATTER_HEADINGS:
            return True
    return False


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------


def detect_document_zones(
    pdf_path: Path,
    profile,
    observations: list,
    body_text_profile,
    max_frontmatter_pages: int = 30,
) -> DocumentZones:
    """
    Bestimmt Frontmatter-, Body- und Backmatter-Zonen.

    Parameter:
        pdf_path             Pfad zum PDF
        profile              DocumentGeometryProfile
        observations         list[PageGeometryObservation]
        body_text_profile    BodyTextProfile (kann None sein)
        max_frontmatter_pages  Obergrenze: Frontmatter endet spätestens hier
    """
    page_count = profile.page_count
    page_height = profile.paper_height
    col_width = (
        profile.vertical_profile.dominant_column_lanes[0].width
        if profile.vertical_profile.dominant_column_lanes else 0.0
    )
    body_x0 = profile.body_region.x0 if profile.body_region else 0.0
    body_x1 = profile.body_region.x1 if profile.body_region else profile.paper_width

    body_start_boundary: ZoneBoundary | None = None
    backmatter_boundary: ZoneBoundary | None = None

    with fitz.open(pdf_path) as doc:

        # ── Pass 1: Body-Beginn vorwärts suchen ─────────────────────────────
        search_limit = min(max_frontmatter_pages, page_count)
        last_frontmatter_page = -1

        for page_idx in range(search_limit):
            page = doc.load_page(page_idx)
            blocks = _blocks_on_page(page)

            if not blocks:
                continue

            # Merke letzte Seite mit Frontmatter-Marker
            if _page_has_frontmatter_marker(blocks):
                last_frontmatter_page = page_idx
                logger.debug("zones: Seite %d hat Frontmatter-Marker", page_idx)
                continue

            # Suche explizites Body-Start-Signal
            for _y0, width, text in blocks:
                score, signal = _score_block_as_body_start(text, _y0, page_height)
                if score >= 0.85:
                    candidate = ZoneBoundary(
                        page_index=page_idx,
                        confidence=score,
                        signal=signal,
                        text_snippet=_first_line(text)[:80],
                    )
                    # Sanity-Check: liegt das Signal zu weit hinter dem letzten
                    # Frontmatter-Marker? Dann ist last_frontmatter + 1 konservativer.
                    if (last_frontmatter_page >= 0
                            and page_idx > last_frontmatter_page + 4):
                        body_start_boundary = ZoneBoundary(
                            page_index=last_frontmatter_page + 1,
                            confidence=0.6,
                            signal="after_frontmatter",
                            text_snippet="",
                        )
                        logger.debug(
                            "zones: Body-Beginn nach Frontmatter Seite %d"
                            " (Signal war zu spät: Seite %d)",
                            last_frontmatter_page + 1, page_idx,
                        )
                    else:
                        body_start_boundary = candidate
                        logger.debug(
                            "zones: Body-Beginn Seite %d via '%s': '%s'",
                            page_idx, signal, candidate.text_snippet,
                        )
                    break

            if body_start_boundary is not None:
                break

        # Fallback: Body beginnt nach dem letzten Frontmatter-Marker
        if body_start_boundary is None:
            body_start = last_frontmatter_page + 1
            body_start_boundary = ZoneBoundary(
                page_index=body_start,
                confidence=0.3 if last_frontmatter_page < 0 else 0.5,
                signal="fallback",
                text_snippet="",
            )
            logger.debug(
                "zones: Body-Beginn Fallback auf Seite %d", body_start,
            )

        body_start = body_start_boundary.page_index

        # ── Pass 2: Backmatter-Beginn rückwärts suchen ──────────────────────
        # Suche vom Ende des Dokuments zurück — stoppt sobald wir
        # weit genug vom Body-Beginn entfernt sind
        min_body_pages = max(3, int(page_count * 0.10))

        for page_idx in range(page_count - 1, body_start + min_body_pages - 1, -1):
            page = doc.load_page(page_idx)
            blocks = _blocks_on_page(page)

            for _y0, _w, text in blocks:
                is_back, term = _is_backmatter_block(text)
                if is_back:
                    backmatter_boundary = ZoneBoundary(
                        page_index=page_idx,
                        confidence=0.95,
                        signal="markword_backmatter",
                        text_snippet=term[:80],
                    )
                    logger.debug(
                        "zones: Backmatter-Beginn Seite %d via '%s'",
                        page_idx, term,
                    )
                    break

            if backmatter_boundary is not None:
                break

    backmatter_start = (
        backmatter_boundary.page_index if backmatter_boundary is not None else None
    )

    zones = DocumentZones(
        page_count=page_count,
        body_start=body_start,
        body_start_boundary=body_start_boundary,
        backmatter_start=backmatter_start,
        backmatter_boundary=backmatter_boundary,
    )

    logger.info(
        "zones: frontmatter=[0..%d] body=[%d..%s] backmatter=[%s..%d]",
        body_start - 1,
        body_start,
        backmatter_start - 1 if backmatter_start else page_count - 1,
        backmatter_start,
        page_count - 1,
    )

    return zones
