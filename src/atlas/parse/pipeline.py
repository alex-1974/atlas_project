from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from .config import ParseConfig
from .errors import AdapterError, ExtractionError
from .geometry import build_geometry_profile, extract_page_blocks
from .logging import get_logger
from .models import MetadataResult, ParseResult, TextSegment

logger = get_logger(__name__)


class ParsePipeline:
    """
    Orchestriert die parsernahe Analyse eines PDF-Dokuments.

    Aktuelle Reihenfolge:
    1. parsernahe Layoutprimitive laden
    2. Geometry Profile bilden
    3. daraus bereinigte Textsegmente erzeugen
    4. erst danach einfache Metadaten-Fallbacks
    """

    PIPELINE_VERSION = "0.3.0"

    def __init__(self, config: ParseConfig | None = None):
        self.config = config or ParseConfig()

    def run(self, pdf_path: Path) -> ParseResult:
        logger.info("Starting parse: %s", pdf_path)

        result = ParseResult(source_path=str(pdf_path))

        try:
            document = self._open_document(pdf_path)

            logger.debug("Building geometry profile")
            geometry = build_geometry_profile(pdf_path)
            result.diagnostics["geometry_profile"] = geometry.to_dict()

            logger.debug("Extracting body-oriented text segments")
            result.text_segments = self._extract_text_segments(pdf_path, geometry)

            logger.debug("Extracting basic metadata")
            result.metadata = self._extract_metadata(document, result.text_segments, pdf_path)

            result.diagnostics.update(
                {
                    "pipeline_version": self.PIPELINE_VERSION,
                    "status": "ok",
                    "page_count": len(document),
                    "text_segment_count": len(result.text_segments),
                }
            )

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

    def _extract_text_segments(self, pdf_path: Path, geometry) -> list[TextSegment]:
        blocks, _page_count, _paper_width, _paper_height = extract_page_blocks(pdf_path)

        body = geometry.body_region
        if body is None:
            return []

        header_band = geometry.header_band
        footer_band = geometry.footer_band
        left_margin = geometry.left_margin_zone
        right_margin = geometry.right_margin_zone

        segments: list[TextSegment] = []

        for block in blocks:
            if block.block_type != 0:
                continue
            text = block.text.strip()
            if not text:
                continue

            if header_band and block.y1 <= header_band.y1 + 2.0:
                continue
            if footer_band and block.y0 >= footer_band.y0 - 2.0:
                continue
            if left_margin and block.x1 <= left_margin.x1:
                continue
            if right_margin and block.x0 >= right_margin.x0:
                continue

            if (
                block.x0 >= body.x0 - 2.0
                and block.x1 <= body.x1 + 2.0
                and block.y0 >= body.y0 - 2.0
                and block.y1 <= body.y1 + 2.0
            ):
                segments.append(
                    TextSegment(
                        text=text,
                        page=block.page_index + 1,
                        kind="body_block",
                        bbox=(block.x0, block.y0, block.x1, block.y1),
                    )
                )

        return segments

    def _extract_metadata(
        self,
        document: fitz.Document,
        segments: list[TextSegment],
        pdf_path: Path,
    ) -> MetadataResult:
        """
        Noch bewusst konservativ:
        - kein blindes Trusten auf PDF-Titel
        - kein aggressives Titelraten
        - Dateiname als letzter Fallback
        """
        metadata = MetadataResult()
        pdf_meta = document.metadata or {}

        title = (pdf_meta.get("title") or "").strip()
        if self._looks_like_plausible_title(title):
            metadata.title = title
        else:
            metadata.title = pdf_path.stem

        creation_date = pdf_meta.get("creationDate") or ""
        year = self._extract_year(creation_date)
        if year:
            metadata.year = year

        return metadata

    def _looks_like_plausible_title(self, value: str) -> bool:
        if not value:
            return False

        bad_suffixes = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
        lowered = value.lower().strip()

        if lowered.endswith(bad_suffixes):
            return False
        if len(value) < 5:
            return False
        if value.count("/") > 0 or value.count("\\") > 0:
            return False

        alpha_chars = sum(ch.isalpha() for ch in value)
        return alpha_chars >= 4

    def _extract_year(self, date_string: str) -> str | None:
        import re

        match = re.search(r"(19|20)\d{2}", date_string)
        return match.group(0) if match else None
