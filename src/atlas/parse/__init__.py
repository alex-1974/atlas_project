"""
atlas.parse

Parsernahe Dokumentanalyse für Atlas.

Dieses Subpackage extrahiert strukturierte, dokumentinterne Informationen
aus einzelnen PDFs. Es ist ein internes Werkzeug von Atlas, nicht dessen Core.

Öffentliche API:
- analyze_document(...)
- ParseResult
"""

from .api import analyze_document
from .models import ParseResult

__all__ = ["analyze_document", "ParseResult"]
