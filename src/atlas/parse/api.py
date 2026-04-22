from __future__ import annotations

from pathlib import Path

from .config import ParseConfig
from .logging import get_logger
from .models import ParseResult
from .pipeline import ParsePipeline

logger = get_logger(__name__)


def analyze_document(
    path: str | Path,
    config: ParseConfig | None = None,
) -> ParseResult:
    """
    Öffentliche API zur Analyse eines PDF-Dokuments.
    """
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"Document not found: {pdf_path}")

    logger.debug("Analyzing document: %s", pdf_path)

    pipeline = ParsePipeline(config=config)
    return pipeline.run(pdf_path)
