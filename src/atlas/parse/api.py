from __future__ import annotations

from pathlib import Path

from .models import ParseResult
from .pipeline import ParsePipeline


def analyze_document(path: str | Path) -> ParseResult:
    """
    Öffentliche API für parsernahe Dokumentanalyse.

    Diese Funktion analysiert ein einzelnes PDF und liefert ein
    strukturiertes ParseResult zurück.

    Hinweise:
    - Keine DB-Zugriffe
    - Keine katalogweite Semantik
    - Keine externe Anreicherung
    """
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"Document not found: {pdf_path}")

    pipeline = ParsePipeline()
    return pipeline.run(pdf_path)
