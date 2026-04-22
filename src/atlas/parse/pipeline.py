"""
atlas.parse.pipeline

Orchestriert die vollständige parse-Pipeline für ein PDF-Dokument.

Öffentliche API:
    result = parse_document(pdf_path)
    result: ParsedDocument

Pipeline-Reihenfolge:
    1. Geometry Profile        (Furniture, Spalten, Body-Region)
    2. Typography Profile      (dom_size, Font-Familie, Bold/Italic)
    3. Document Zones          (Frontmatter / Body / Backmatter)
    4. Document Type Hint      (article/book/report/collection)
    5. Metadata                (Titel, Autoren, Identifier — mit Reconciliation)
    6. Sections                (hierarchischer Section-Tree)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .geometry import build_document_geometry_profile
from .typography import extract_body_text_profile
from .document_zones import detect_document_zones
from .document_type_hints import infer_document_type_hint, DocumentTypeHint
from .metadata import extract_metadata, ExtractedMetadata
from .sections import extract_sections, Section
from .logging import get_logger

logger = get_logger(__name__)

PIPELINE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class ParsedDocument:
    """
    Vollständiges Ergebnis der parse-Pipeline.

    Alle Felder sind optional — bei Scan-PDFs oder fehlerhaften Dokumenten
    können einzelne Felder None/leer sein. `pipeline_ok` gibt an ob die
    Pipeline ohne Fehler durchgelaufen ist.
    """
    source_path:   str

    # Rohe Profil-Objekte (für Downstream-Nutzung)
    geometry_profile: Any | None = None
    body_text_profile: Any | None = None
    zones: Any | None = None
    doc_hint: DocumentTypeHint | None = None

    # Extrahierte Metadaten
    metadata: ExtractedMetadata | None = None

    # Section-Tree
    sections: list[Section] = field(default_factory=list)

    # Diagnostik
    page_count:  int = 0
    is_scan:     bool = False
    doc_class:   str | None = None
    pipeline_ok: bool = True
    error:       str | None = None
    pipeline_version: str = PIPELINE_VERSION

    # Bequeme Properties
    @property
    def title(self) -> str | None:
        return self.metadata.title if self.metadata else None

    @property
    def authors(self) -> list[str]:
        return self.metadata.authors if self.metadata else []

    @property
    def year(self) -> int | None:
        return self.metadata.year if self.metadata else None

    @property
    def doi(self) -> str | None:
        return self.metadata.doi if self.metadata else None

    @property
    def isbn(self) -> str | None:
        return self.metadata.isbn if self.metadata else None

    @property
    def issn(self) -> str | None:
        return self.metadata.issn if self.metadata else None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def parse_document(
    pdf_path: Path | str,
    max_section_level: int | None = None,
) -> ParsedDocument:
    """
    Führt die vollständige parse-Pipeline für ein PDF-Dokument aus.

    Args:
        pdf_path: Pfad zum PDF
        max_section_level: Maximale Section-Tiefe (None = auto aus doc_class)

    Returns:
        ParsedDocument mit allen extrahierten Daten.
        Bei Fehlern: pipeline_ok=False, error=Fehlermeldung.
    """
    pdf_path = Path(pdf_path)
    result   = ParsedDocument(source_path=str(pdf_path))

    logger.info("parse_document: %s", pdf_path.name)

    try:
        # ── 1. Geometry ───────────────────────────────────────────────────
        logger.debug("parse: geometry")
        profile, observations = build_document_geometry_profile(pdf_path)
        result.geometry_profile = profile
        result.page_count       = profile.page_count

        fp  = profile.furniture_profile
        vp  = profile.vertical_profile
        pfp = profile.page_format_profile
        col_width = (
            vp.dominant_column_lanes[0].width
            if vp.dominant_column_lanes else 0.0
        )

        # ── 2. Typography ─────────────────────────────────────────────────
        logger.debug("parse: typography")
        tp = extract_body_text_profile(
            pdf_path=pdf_path,
            body_x0=profile.body_region.x0,
            body_y0=profile.body_region.y0,
            body_x1=profile.body_region.x1,
            body_y1=profile.body_region.y1,
            col_width=col_width,
            header_y1=fp.header_band.y1 if fp.header_band else None,
            footer_y0=fp.footer_band.y0 if fp.footer_band else None,
            profile_page_indexes=pfp.profile_page_indexes if pfp else None,
            page_count=profile.page_count,
        )
        result.body_text_profile = tp
        result.is_scan = (tp is None or tp.dominant_size <= 0.0)

        # ── 3. Zones ──────────────────────────────────────────────────────
        logger.debug("parse: zones")
        zones = detect_document_zones(pdf_path, profile, observations, tp)
        result.zones = zones

        # ── 4. Document Type Hint ─────────────────────────────────────────
        logger.debug("parse: document type hint")
        hint = infer_document_type_hint(
            profile, zones, observations, pdf_path=pdf_path
        )
        result.doc_hint  = hint
        result.doc_class = hint.doc_class

        # ── 5. Metadata ───────────────────────────────────────────────────
        logger.debug("parse: metadata")
        meta = extract_metadata(
            pdf_path, profile, zones, tp, observations=observations
        )
        result.metadata = meta

        # ── 6. Sections ───────────────────────────────────────────────────
        logger.debug("parse: sections")
        sections = extract_sections(
            pdf_path, profile, zones, tp,
            doc_hint=hint,
            max_level=max_section_level,
        )
        result.sections = sections

        logger.info(
            "parse_document: %s — %s  title=%r  sections=%d  pages=%d",
            pdf_path.name,
            hint.doc_class,
            meta.title[:40] if meta.title else None,
            len(sections),
            profile.page_count,
        )

    except Exception as exc:
        logger.exception("parse_document failed: %s", pdf_path)
        result.pipeline_ok = False
        result.error       = f"{type(exc).__name__}: {exc}"

    return result
