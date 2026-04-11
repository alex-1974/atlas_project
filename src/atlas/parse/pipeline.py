from __future__ import annotations

from pathlib import Path

from .config import ParseConfig
from .logging import get_logger
from .models import MetadataResult, ParseResult, TextSegment

logger = get_logger(__name__)


class ParsePipeline:
    """
    Orchestriert die parsernahe Analyse eines PDF-Dokuments.
    """

    def __init__(self, config: ParseConfig | None = None):
        self.config = config or ParseConfig()

    def run(self, pdf_path: Path) -> ParseResult:
        logger.info("Starting parse: %s", pdf_path)

        result = ParseResult(source_path=str(pdf_path))

        try:
            # Placeholder für zukünftige Adapter
            logger.debug("Extracting metadata")
            result.metadata = MetadataResult(title=pdf_path.stem)

            logger.debug("Creating placeholder text segment")
            result.text_segments.append(
                TextSegment(
                    text="",
                    page=None,
                    kind="document_placeholder",
                )
            )

            result.diagnostics["pipeline_version"] = "0.1.0"
            result.diagnostics["status"] = "stub"

            logger.info("Finished parse: %s", pdf_path)

        except Exception as exc:
            logger.exception("Parsing failed for %s", pdf_path)
            raise

        return result
