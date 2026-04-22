"""
Custom exceptions for atlas.parse.
"""


class ParseError(Exception):
    """Basisklasse für Parserfehler."""


class UnsupportedFormatError(ParseError):
    """Das Dokumentformat wird nicht unterstützt."""


class AdapterError(ParseError):
    """Fehler beim Zugriff auf das PDF-Backend."""


class ExtractionError(ParseError):
    """Fehler während der Extraktion."""


class StructureDetectionError(ParseError):
    """Fehler bei der Strukturerkennung."""
