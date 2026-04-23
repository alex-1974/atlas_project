"""
atlas.semantic.section_text

Extrahiert den Fließtext jedes Abschnitts direkt aus dem PDF.
Nutzt page_start/page_end aus du_section_tree — keine Abhängigkeit
von du_blocks oder du_block_roles.

Öffentliche API:
    texts = extract_section_texts(pdf_path, conn, document_id)
    # → {section_node_id: SectionText}

    text = extract_window_texts(pdf_path, profile, window_words=400)
    # → [SectionText] für Dokumente ohne Heading-Struktur
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class SectionText:
    """Text eines Abschnitts mit Metadaten."""
    section_node_id: int | None    # None bei Fenster-Segmenten
    level: int
    title: str
    page_start: int
    page_end: int
    text: str                      # Fließtext des Abschnitts
    word_count: int = 0
    language_hint: str | None = None  # wird von semantic.language befüllt

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split()) if self.text else 0


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _span_text(span: dict) -> str:
    t = span.get("text", "")
    if t:
        return t
    return "".join(c.get("c", "") for c in span.get("chars", []))


def _extract_page_text(
    page: fitz.Page,
    body_x0: float = 0.0,
    body_x1: float = 9999.0,
    header_y1: float | None = None,
    footer_y0: float | None = None,
) -> str:
    """Extrahiert Fließtext einer Seite, Furniture ausgeschlossen."""
    raw = page.get_text("rawdict")
    parts = []

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox", [0, 0, 0, 0])
        y0, y1 = bbox[1], bbox[3]

        # Header/Footer ausschließen
        if header_y1 is not None and y1 <= header_y1 * 1.05:
            continue
        if footer_y0 is not None and y0 >= footer_y0 * 0.95:
            continue

        text = " ".join(
            _span_text(sp).strip()
            for line in block.get("lines", [])
            for sp in line.get("spans", [])
            if _span_text(sp).strip()
        )
        if text:
            parts.append(text)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Hauptfunktionen
# ---------------------------------------------------------------------------

def extract_section_texts(
    pdf_path: Path,
    conn: sqlite3.Connection,
    document_id: str,
    profile=None,
    min_words: int = 20,
    max_words_per_section: int = 2000,
) -> dict[int, SectionText]:
    """
    Extrahiert den Fließtext jedes Abschnitts aus dem PDF.

    Nutzt page_start/page_end aus du_section_tree.
    Abschnitte mit < min_words werden mit dem Titel als Text befüllt.

    Args:
        pdf_path:  Pfad zum PDF
        conn:      SQLite-Verbindung
        document_id: Dokument-ID
        profile:   DocumentGeometryProfile (optional, für Header/Footer)
        min_words: Minimale Wortanzahl für Textextraktion
        max_words_per_section: Maximale Wortanzahl pro Abschnitt

    Returns:
        {section_node_id: SectionText}
    """
    # Header/Footer-Grenzen aus Profil
    header_y1 = footer_y0 = None
    if profile is not None:
        fp = profile.furniture_profile
        if fp and fp.header_band:
            header_y1 = fp.header_band.y1
        if fp and fp.footer_band:
            footer_y0 = fp.footer_band.y0

    # Sections aus DB laden
    sections = conn.execute(
        """
        SELECT section_node_id, level, title,
               page_start, page_end, start_block_index
        FROM du_section_tree
        WHERE document_id = ?
        ORDER BY start_block_index
        """,
        (document_id,),
    ).fetchall()

    if not sections:
        return {}

    results: dict[int, SectionText] = {}

    with fitz.open(pdf_path) as doc:
        n_pages = len(doc)

        for i, sec in enumerate(sections):
            node_id    = sec["section_node_id"]
            level      = sec["level"] or 1
            title      = sec["title"] or ""
            page_start = sec["page_start"] or 0
            # page_end: bis zur nächsten Sektion oder Dokumentende
            if sec["page_end"] is not None:
                page_end = sec["page_end"]
            elif i + 1 < len(sections):
                page_end = sections[i + 1]["page_start"] or page_start
            else:
                page_end = n_pages - 1

            # Seiten sammeln (max 10 Seiten pro Abschnitt)
            pages_to_read = range(
                max(0, page_start),
                min(n_pages, page_end + 1, page_start + 10)
            )

            page_texts = []
            for page_idx in pages_to_read:
                page = doc.load_page(page_idx)
                page_texts.append(
                    _extract_page_text(page, header_y1=header_y1,
                                       footer_y0=footer_y0)
                )

            raw_text = " ".join(page_texts)
            # Auf max_words_per_section kürzen
            words = raw_text.split()
            if len(words) > max_words_per_section:
                raw_text = " ".join(words[:max_words_per_section])

            # Zu kurz → Titel als Fallback
            if len(raw_text.split()) < min_words:
                raw_text = title

            results[node_id] = SectionText(
                section_node_id=node_id,
                level=level,
                title=title,
                page_start=page_start,
                page_end=page_end,
                text=raw_text,
            )

    return results


def extract_window_texts(
    pdf_path: Path,
    profile=None,
    window_words: int = 400,
    overlap_words: int = 50,
) -> list[SectionText]:
    """
    Fallback für Dokumente ohne Heading-Struktur.

    Teilt den Dokumenttext in überlappende Fenster von window_words Wörtern.
    Jedes Fenster wird als eigener "Abschnitt" behandelt.

    Args:
        pdf_path:     Pfad zum PDF
        profile:      DocumentGeometryProfile (optional)
        window_words: Fenstergröße in Wörtern
        overlap_words: Überlapp zwischen Fenstern

    Returns:
        Liste von SectionText-Objekten
    """
    header_y1 = footer_y0 = None
    if profile is not None:
        fp = profile.furniture_profile
        if fp and fp.header_band:
            header_y1 = fp.header_band.y1
        if fp and fp.footer_band:
            footer_y0 = fp.footer_band.y0

    all_words: list[tuple[str, int]] = []  # (word, page_idx)

    with fitz.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            text = _extract_page_text(page, header_y1=header_y1,
                                       footer_y0=footer_y0)
            for word in text.split():
                all_words.append((word, page_idx))

    if not all_words:
        return []

    results: list[SectionText] = []
    step = window_words - overlap_words
    i = 0
    window_num = 0

    while i < len(all_words):
        window = all_words[i:i + window_words]
        if not window:
            break
        text = " ".join(w for w, _ in window)
        page_start = window[0][1]
        page_end   = window[-1][1]
        window_num += 1

        results.append(SectionText(
            section_node_id=None,
            level=1,
            title=f"Fenster {window_num} (S. {page_start + 1}–{page_end + 1})",
            page_start=page_start,
            page_end=page_end,
            text=text,
        ))
        i += step

    return results
