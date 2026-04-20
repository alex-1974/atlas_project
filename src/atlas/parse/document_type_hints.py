"""
atlas.parse.document_type_hints

Leitet aus Geometry-Profil, Zonen und Dokumentstruktur einen groben
Dokumenttyp-Hinweis ab. Kein vollständiger Klassifikator — nur
genug um die Metadaten-Extraktionsstrategie zu steuern.

Signale:
    - Seitenanzahl
    - Frontmatter-Umfang
    - Spaltenanzahl
    - Scan-Cover-Erkennung (Seite 0 = Digitalisierungs-Deckblatt)
    - Strukturierungstiefe (TOC, Nummerierungstiefe, Backmatter-Reichtum)
    - Markword-Dichte

Öffentliche API:
    hint = infer_document_type_hint(profile, zones, observations, pdf_path)
    hint.doc_class          # "article" | "book" | "report" | "collection"
    hint.scan_cover         # True wenn Seite 0 = Scan-Deckblatt
    hint.structure_depth    # 0=kaum, 1=flach, 2=mittel, 3=tief
    hint.has_toc            # Inhaltsverzeichnis erkannt
    hint.title_search_pages
    hint.author_search_pages
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from .logging import get_logger
from .section_labels import (
    ALL_BACK_MATTER_HEADINGS,
    BODY_START_NUMBERED_RE,
    BACKMATTER_RE,
    TOC_HEADINGS,
    TOC_RE,
)

logger = get_logger(__name__)

# Tiefe Nummerierung: "1.1", "1.1.1", "2.3.4"
_DEEP_NUMBER_RE = re.compile(r"^\s*\d+\.\d+(?:\.\d+)*\s+\S")


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DocumentTypeHint:
    """
    Grober Dokumenttyp-Hinweis für die Metadaten-Extraktion.

    doc_class:
        "article"    — kurzer Artikel (< 30S), oft in Zeitschrift
        "book"       — Monografie (> 80S, tiefes Frontmatter, tiefe Struktur)
        "report"     — Bericht/Heft (mittel, institutioneller Autor möglich)
        "collection" — Sammelband mit mehreren Autoren

    scan_cover:
        True wenn Seite 0 wahrscheinlich ein Scan-Deckblatt ist.

    structure_depth:
        0 = kaum strukturiert (reiner Fließtext, keine Überschriften)
        1 = flach (3-8 unnummerierte oder einfach nummerierte Abschnitte)
        2 = mittel (nummerierte Abschnitte bis L2)
        3 = tief (Nummerierung bis L3+, Inhaltsverzeichnis)

    has_toc: Inhaltsverzeichnis im Frontmatter erkannt.
    backmatter_richness: Anzahl verschiedener Backmatter-Marker.
    """
    doc_class: str
    scan_cover: bool
    structure_depth: int                      # 0–3
    has_toc: bool
    backmatter_richness: int                  # 0–3
    title_search_pages: list[int]
    author_search_pages: list[int]
    confidence: float
    reasoning: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Struktur-Analyse (PDF-Scan)
# ---------------------------------------------------------------------------

def _analyze_structure(
    pdf_path: Path,
    page_count: int,
    body_start: int,
    backmatter_start: int | None,
) -> tuple[int, bool, int]:
    """
    Analysiert Strukturierungstiefe, TOC-Vorhandensein und Backmatter-Reichtum.

    Scannt:
    - Frontmatter auf TOC-Marker
    - Erste 15 Body-Seiten auf Nummerierungstiefe
    - Letzte 20 Seiten auf Backmatter-Marker-Vielfalt

    Gibt (structure_depth, has_toc, backmatter_richness) zurück.
    """
    has_toc = False
    max_depth = 0
    backmatter_markers: set[str] = set()

    # Profilseiten für Strukturanalyse
    fm_scan  = list(range(0, min(body_start, page_count)))
    body_scan = list(range(body_start, min(body_start + 15, page_count)))
    bm_scan  = list(range(max(0, page_count - 20), page_count))

    scan_pages = sorted(set(fm_scan + body_scan + bm_scan))

    try:
        with fitz.open(pdf_path) as doc:
            for page_idx in scan_pages:
                if page_idx >= len(doc):
                    continue
                page = doc.load_page(page_idx)
                blocks = page.get_text("blocks")

                for b in blocks:
                    if b[6] != 0:
                        continue
                    text = b[4].strip()
                    if not text:
                        continue
                    first = text.splitlines()[0].strip() if text else ""

                    # TOC im Frontmatter
                    if page_idx < body_start:
                        norm = " ".join(first.lower().split())
                        if TOC_RE.match(first) and norm in TOC_HEADINGS:
                            has_toc = True

                    # Nummerierungstiefe in Body-Seiten
                    if page_idx in set(body_scan):
                        if _DEEP_NUMBER_RE.match(first):
                            # Zähle Ebenen: "1.2.3" → 3
                            m = re.match(r"^\s*(\d+(?:\.\d+)*)", first)
                            if m:
                                depth = m.group(1).count('.') + 1
                                max_depth = max(max_depth, depth)
                        elif BODY_START_NUMBERED_RE.match(first):
                            max_depth = max(max_depth, 1)

                    # Backmatter-Marker-Vielfalt
                    if page_idx in set(bm_scan):
                        norm = " ".join(first.lower().split())
                        if BACKMATTER_RE.match(first) and norm in ALL_BACK_MATTER_HEADINGS:
                            backmatter_markers.add(norm)

    except Exception as e:
        logger.debug("structure_analysis: Fehler — %s", e)

    # Strukturtiefe: 0=keine, 1=flach, 2=mittel, 3=tief
    if max_depth >= 3 or (max_depth >= 2 and has_toc):
        structure_depth = 3
    elif max_depth == 2 or (max_depth == 1 and has_toc):
        structure_depth = 2
    elif max_depth == 1:
        structure_depth = 1
    else:
        structure_depth = 0

    backmatter_richness = min(len(backmatter_markers), 3)

    return structure_depth, has_toc, backmatter_richness


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def infer_document_type_hint(
    profile,
    zones,
    observations: list,
    pdf_path: Path | None = None,
) -> DocumentTypeHint:
    """
    Leitet DocumentTypeHint ab.

    Wenn pdf_path übergeben wird, wird eine Strukturanalyse durchgeführt
    (TOC, Nummerierungstiefe, Backmatter-Reichtum). Ohne pdf_path nur
    geometrische Signale.
    """
    page_count  = profile.page_count
    fm_pages    = len(zones.frontmatter_pages)
    col_count   = profile.vertical_profile.dominant_column_count
    body_start  = zones.body_start
    bm_start    = zones.backmatter_start
    bm_signal   = zones.body_start_boundary.signal

    reasoning: list[str] = []

    # ── Scan-Cover-Erkennung ─────────────────────────────────────────────────
    scan_cover = False
    page0_obs = observations[0].vertical if observations else None
    if (fm_pages >= 1
            and page_count > 20
            and page0_obs is not None
            and page0_obs.observed_column_count == 0
            and bm_signal in ("fallback", "after_frontmatter", "markword_body_start")):
        # Zusatzcheck: wenn Seite 0 einen echten großen Textblock hat
        # (ratio > 2.0), ist es wahrscheinlich ein echter Titel, kein Scan-Cover.
        # Das unterscheidet Edinburgh (echter Artikel-Titel auf Seite 1)
        # von Digitalisierungs-Deckblättern.
        # Wir prüfen das nicht hier (kein PDF-Zugriff) — wird durch
        # den Title-Kandidaten auf Seite 0 implizit korrigiert.
        scan_cover = True
        reasoning.append(f"Seite 0: 0 Spalten + fm={fm_pages} → Scan-Cover")

    # ── Strukturanalyse ──────────────────────────────────────────────────────
    if pdf_path is not None:
        structure_depth, has_toc, bm_richness = _analyze_structure(
            pdf_path, page_count, body_start, bm_start
        )
    else:
        structure_depth = 1 if fm_pages > 3 else 0
        has_toc = False
        bm_richness = 1 if bm_start is not None else 0

    if has_toc:
        reasoning.append("TOC erkannt")
    if structure_depth >= 2:
        reasoning.append(f"Nummerierungstiefe={structure_depth}")
    if bm_richness >= 2:
        reasoning.append(f"Backmatter-Reichtum={bm_richness}")

    # ── Dokumentklasse — Scoring ─────────────────────────────────────────────
    # Punkte-System: jedes Signal stimmt für eine Klasse

    scores = {"article": 0.0, "book": 0.0, "report": 0.0, "collection": 0.0}

    # Seitenanzahl
    if page_count <= 25:
        scores["article"] += 3.0
    elif page_count <= 50:
        scores["article"] += 1.5
        scores["report"]  += 1.0
    elif page_count <= 120:
        scores["report"]     += 2.0
        scores["collection"] += 1.5
    else:
        scores["book"]       += 3.0
        scores["collection"] += 1.0

    # Frontmatter-Umfang
    if fm_pages == 0:
        scores["article"] += 1.5
    elif fm_pages <= 3:
        scores["article"] += 0.5
        scores["report"]  += 0.5
    elif fm_pages <= 8:
        scores["report"]     += 1.5
        scores["collection"] += 1.0
    else:
        scores["book"]       += 2.0
        scores["collection"] += 1.5

    # Spaltenanzahl
    if col_count == 2:
        scores["article"] += 1.0

    # Strukturtiefe
    if structure_depth == 0:
        scores["article"] += 1.0
    elif structure_depth == 1:
        scores["article"] += 0.5
        scores["report"]  += 0.5
    elif structure_depth == 2:
        scores["report"]     += 1.0
        scores["collection"] += 0.5
    else:  # 3
        scores["book"]       += 2.0
        scores["collection"] += 1.0

    # TOC
    if has_toc:
        scores["book"]       += 1.5
        scores["collection"] += 1.0
        scores["report"]     += 0.5

    # Backmatter-Reichtum
    if bm_richness >= 2:
        scores["book"] += 1.5
    elif bm_richness == 1:
        scores["report"] += 0.5

    # Gewinner
    doc_class = max(scores, key=lambda k: scores[k])
    total = sum(scores.values()) or 1.0
    confidence = round(scores[doc_class] / total, 2)
    confidence = min(0.95, max(0.4, confidence))

    reasoning.append(
        f"Scores: " + " ".join(f"{k}={v:.1f}" for k, v in sorted(scores.items()))
    )

    # ── Such-Seiten ──────────────────────────────────────────────────────────
    if doc_class == "article":
        if scan_cover:
            title_pages  = list(range(1, min(3, page_count)))
            author_pages = list(range(1, min(4, page_count)))
        else:
            title_pages  = list(range(0, min(2, page_count)))
            author_pages = list(range(0, min(3, page_count)))

    elif doc_class == "book":
        # Seite 0 immer einschließen — kann echte Titelseite sein
        title_pages  = list(range(0, min(5, page_count)))
        author_pages = list(range(1, min(6, page_count)))

    elif doc_class == "collection":
        title_pages  = list(range(0, min(body_start + 3, page_count)))
        author_pages = list(range(body_start, min(body_start + 5, page_count)))

    else:  # report
        if scan_cover:
            title_pages  = list(range(1, min(4, page_count)))
            author_pages = list(range(1, min(5, page_count)))
        else:
            title_pages  = list(range(0, min(3, page_count)))
            author_pages = list(range(0, min(5, page_count)))

    def _dedup(pages: list[int]) -> list[int]:
        seen: set[int] = set()
        return [p for p in pages if p not in seen and not seen.add(p)  # type: ignore[func-returns-value]
                and 0 <= p < page_count]

    hint = DocumentTypeHint(
        doc_class=doc_class,
        scan_cover=scan_cover,
        structure_depth=structure_depth,
        has_toc=has_toc,
        backmatter_richness=bm_richness,
        title_search_pages=_dedup(title_pages),
        author_search_pages=_dedup(author_pages),
        confidence=confidence,
        reasoning=reasoning,
    )

    logger.debug(
        "doc_type: class=%s depth=%d toc=%s bm=%d scan=%s conf=%.2f | %s",
        doc_class, structure_depth, has_toc, bm_richness, scan_cover,
        confidence, "; ".join(reasoning[:3]),
    )

    return hint
