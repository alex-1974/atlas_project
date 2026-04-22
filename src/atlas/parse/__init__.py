"""
atlas.parse

Parsernahe Dokumentanalyse für Atlas.

Dieses Subpackage extrahiert strukturierte, dokumentinterne Informationen
aus einzelnen PDFs. Es ist ein internes Werkzeug von Atlas, nicht dessen Core.

Öffentliche API:
- analyze_document(...)
- ParseResult
"""

from __future__ import annotations

__all__ = ["analyze_document"]


def analyze_document(*args, **kwargs):
    from .api import analyze_document as _analyze_document
    return _analyze_document(*args, **kwargs)
