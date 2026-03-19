from __future__ import annotations

import re


ABSTRACT_RE = re.compile(r"^\s*(abstract|summary|zusammenfassung)\b", re.IGNORECASE)
KEYWORDS_RE = re.compile(r"^\s*(keywords|schlagw[oö]rter)\b", re.IGNORECASE)
REFERENCES_RE = re.compile(r"^\s*(references|bibliography|works cited|literatur|literaturverzeichnis)\b", re.IGNORECASE)
FIGURE_RE = re.compile(r"^\s*(figure|fig\.?)\b", re.IGNORECASE)
TABLE_RE = re.compile(r"^\s*table\b", re.IGNORECASE)
APPENDIX_RE = re.compile(r"^\s*appendix\b", re.IGNORECASE)
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
CIT_BRACKET_RE = re.compile(r"\[[0-9,\- ]+\]")
CIT_AUTH_YEAR_RE = re.compile(r"\b[A-Z][a-zA-Z-]+(?:\s+and\s+[A-Z][a-zA-Z-]+)?\s*\((?:19|20)\d{2}\)")


def compute_semantic_micro(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    rows: list[dict] = []

    for block in blocks:
        text = (block.get("text") or "").strip()

        rows.append(
            {
                "block_id": block["block_id"],
                "is_abstract_marker": bool(ABSTRACT_RE.search(text)),
                "is_keywords_marker": bool(KEYWORDS_RE.search(text)),
                "is_references_marker": bool(REFERENCES_RE.search(text)),
                "is_figure_marker": bool(FIGURE_RE.search(text)),
                "is_table_marker": bool(TABLE_RE.search(text)),
                "is_appendix_marker": bool(APPENDIX_RE.search(text)),
                "contains_doi": bool(DOI_RE.search(text)),
                "contains_year": bool(YEAR_RE.search(text)),
                "contains_citation_bracket": bool(CIT_BRACKET_RE.search(text)),
                "contains_citation_author_year": bool(CIT_AUTH_YEAR_RE.search(text)),
            }
        )

    repo.store_semantic_micro_features(document_id, rows)
