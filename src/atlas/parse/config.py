"""
Configuration utilities for atlas.parse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ParseConfig:
    """
    Konfiguration der ParsePipeline.
    """
    enable_debug_logging: bool = False
    extract_references: bool = True
    extract_identifiers: bool = True
    detect_document_type: bool = True
    build_section_tree: bool = True
    segment_paragraphs: bool = True
