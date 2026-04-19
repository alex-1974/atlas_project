from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from .config import ParseConfig
from .errors import AdapterError, ExtractionError
from .geometry import build_document_geometry_profile, extract_page_blocks
from .logging import get_logger
from .models import MetadataResult, ParseResult, TextSegment

logger = get_logger(__name__)


class ParsePipeline:
    """
    Orchestriert die parsernahe Analyse eines PDF-Dokuments.

    Reihenfolge:
    1. Geometry Profile aufbauen (Furniture, Spalten, Body-Region)
    2. Textsegmente aus Body extrahieren (Header/Footer/Marginalien ausgeklammert)
    3. Metadaten-Fallbacks
    """

    PIPELINE_VERSION = "0.4.0"

    def __init__(self, config: ParseConfig | None = None):
        self.config = config or ParseConfig()

    def run(self, pdf_path: Path) -> ParseResult:
        logger.info("Starting parse: %s", pdf_path)

        result = ParseResult(source_path=str(pdf_path))

        try:
            document = self._open_document(pdf_path)

            logger.debug("Building geometry profile")
            profile, observations = build_document_geometry_profile(pdf_path)
            result.diagnostics["geometry_profile"] = profile.to_dict()

            logger.debug("Extracting body-oriented text segments")
            result.text_segments = self._extract_text_segments(pdf_path, profile)

            logger.debug("Extracting basic metadata")
            result.metadata = self._extract_metadata(document, result.text_segments, pdf_path)

            result.diagnostics.update({
                "pipeline_version": self.PIPELINE_VERSION,
                "status": "ok",
                "page_count": len(document),
                "text_segment_count": len(result.text_segments),
            })

            document.close()
            logger.info("Finished parse: %s", pdf_path)

        except AdapterError:
            raise
        except Exception as exc:
            logger.exception("Parsing failed for %s", pdf_path)
            raise ExtractionError(str(exc)) from exc

        return result

    def _open_document(self, pdf_path: Path) -> fitz.Document:
        try:
            return fitz.open(pdf_path)
        except Exception as exc:
            raise AdapterError(f"Failed to open PDF: {pdf_path}") from exc

    def _extract_text_segments(self, pdf_path: Path, profile) -> list[TextSegment]:
        """
        Extrahiert Textsegmente aus dem Body-Bereich.

        Nutzt das Geometry-Profil für:
        - Header/Footer-Ausschluss (Furniture-Bänder)
        - Body-Region als primärer Clip
        - Spalteninformation für zukünftige Segmentierung
        """
        blocks, _page_count, _paper_width, _paper_height = extract_page_blocks(pdf_path)

        body = profile.body_region
        if body is None:
            return []

        fp = profile.furniture_profile
        header_band = fp.header_band
        footer_band = fp.footer_band

        segments: list[TextSegment] = []

        for block in blocks:
            if block.block_type != 0:
                continue
            text = block.text.strip()
            if not text:
                continue

            # Furniture ausschließen
            if header_band and block.y1 <= header_band.y1 + 2.0:
                continue
            if footer_band and block.y0 >= footer_band.y0 - 2.0:
                continue

            # Body-Region prüfen
            if (
                block.x0 >= body.x0 - 2.0
                and block.x1 <= body.x1 + 2.0
                and block.y0 >= body.y0 - 2.0
                and block.y1 <= body.y1 + 2.0
            ):
                segments.append(TextSegment(
                    text=text,
                    page=block.page_index + 1,
                    kind="body_block",
                    bbox=(block.x0, block.y0, block.x1, block.y1),
                ))

        return segments

    def _extract_metadata(
        self,
        document: fitz.Document,
        segments: list[TextSegment],
        pdf_path: Path,
    ) -> MetadataResult:
        """
        Konservative Metadaten-Extraktion.
        PDF-Titel nur wenn plausibel, sonst Dateiname als Fallback.
        """
        metadata = MetadataResult()
        pdf_meta = document.metadata or {}

        title = (pdf_meta.get("title") or "").strip()
        metadata.title = title if self._looks_like_plausible_title(title) else pdf_path.stem

        year = self._extract_year(pdf_meta.get("creationDate") or "")
        if year:
            metadata.year = year

        return metadata

    def _looks_like_plausible_title(self, value: str) -> bool:
        if not value or len(value) < 5:
            return False
        bad_suffixes = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
        if value.lower().strip().endswith(bad_suffixes):
            return False
        if "/" in value or "\\" in value:
            return False
        return sum(ch.isalpha() for ch in value) >= 4

    def _extract_year(self, date_string: str) -> str | None:
        import re
        match = re.search(r"(19|20)\d{2}", date_string)
        return match.group(0) if match else None
