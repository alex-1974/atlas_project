from __future__ import annotations

from pathlib import Path

from .models import MetadataResult, ParseResult, TextSegment


class ParsePipeline:
    """
    Minimale Startpipeline für atlas.parse.

    Ziel dieser ersten Version:
    - stabile API
    - saubere Modulgrenzen
    - keine Altstruktur mitschleppen

    Spätere Erweiterungen:
    - PyMuPDF-Adapter
    - Segmentierung
    - Struktur- und Zonenlogik
    - Referenzanalyse
    - Dokumenttyp-Klassifikation
    """

    def run(self, pdf_path: Path) -> ParseResult:
        result = ParseResult(source_path=str(pdf_path))

        # TODO:
        # Adapter-basierte PDF-/Text-Akquisition hier einhängen.
        # Für den Start bleibt das Ergebnis minimal und stabil.
        result.metadata = MetadataResult(
            title=pdf_path.stem,
        )

        result.text_segments.append(
            TextSegment(
                text="",
                page=None,
                kind="document_placeholder",
            )
        )

        result.diagnostics["pipeline_version"] = "0.1.0"
        result.diagnostics["status"] = "stub"

        return result
