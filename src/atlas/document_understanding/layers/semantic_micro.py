# src/atlas/document_understanding/layers/semantic_micro.py

from __future__ import annotations

import re

from atlas.document_understanding.persistence.repository import Repository


ABSTRACT_RE = re.compile(r"^\s*abstract\b", re.IGNORECASE)
KEYWORDS_RE = re.compile(r"^\s*(keywords?|index terms?)\b", re.IGNORECASE)

REFERENCES_RE = re.compile(r"^\s*(references|bibliography|literature cited)\b", re.IGNORECASE)

FIGURE_RE = re.compile(r"^\s*(figure|fig\.?)\s*\d+", re.IGNORECASE)
TABLE_RE = re.compile(r"^\s*(table)\s*\d+", re.IGNORECASE)

APPENDIX_RE = re.compile(r"^\s*appendix\b", re.IGNORECASE)

CITATION_BRACKET_RE = re.compile(r"\[[0-9,\s\-]+\]")
CITATION_AUTHOR_YEAR_RE = re.compile(
    r"\b[A-Z][A-Za-z\-]+(?:\s+and\s+[A-Z][A-Za-z\-]+)?\s*\(\d{4}\)"
)

DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)

YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")


def compute_semantic_micro(repository: Repository, doc_id: int) -> None:
    """
    Detect explicit textual semantic markers.

    These are strong hints for later inference stages.
    """

    blocks = repository.fetch_blocks(doc_id)
    if not blocks:
        return

    rows = []

    for block in blocks:
        text = (block.get("text") or "").strip()

        is_abstract_marker = bool(ABSTRACT_RE.match(text))
        is_keywords_marker = bool(KEYWORDS_RE.match(text))

        is_references_marker = bool(REFERENCES_RE.match(text))

        is_figure_marker = bool(FIGURE_RE.match(text))
        is_table_marker = bool(TABLE_RE.match(text))

        is_appendix_marker = bool(APPENDIX_RE.match(text))

        contains_doi = bool(DOI_RE.search(text))
        contains_year = bool(YEAR_RE.search(text))

        contains_citation_bracket = bool(CITATION_BRACKET_RE.search(text))
        contains_citation_author_year = bool(CITATION_AUTHOR_YEAR_RE.search(text))

        rows.append(
            {
                "block_id": block["block_id"],
                "is_abstract_marker": is_abstract_marker,
                "is_keywords_marker": is_keywords_marker,
                "is_references_marker": is_references_marker,
                "is_figure_marker": is_figure_marker,
                "is_table_marker": is_table_marker,
                "is_appendix_marker": is_appendix_marker,
                "contains_doi": contains_doi,
                "contains_year": contains_year,
                "contains_citation_bracket": contains_citation_bracket,
                "contains_citation_author_year": contains_citation_author_year,
            }
        )

    repository.store_semantic_micro_features(doc_id, rows)
