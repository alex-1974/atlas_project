# src/atlas/understanding/measure/semantic_micro.py
"""Layer 1 — regex-based semantic anchor markers per block.

Purely text-based. Reads du_blocks, writes du_block_semantic_micro.
No geometric or typographic knowledge — this module runs independently
of all other Layer 1 modules.
"""
from __future__ import annotations

import re
import sqlite3


from atlas.understanding.core.section_labels import (
    ABSTRACT_RE   as _ABSTRACT_RE,
    KEYWORDS_RE   as _KEYWORDS_RE,
    REFERENCES_RE as _REFERENCES_RE,
    FIGURE_RE     as _FIGURE_RE,
    TABLE_RE      as _TABLE_RE,
    APPENDIX_RE   as _APPENDIX_RE,
)
from atlas.understanding.core.text_patterns import contains_chapter_number as _contains_chapter_number
_DOI_RE        = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
_YEAR_RE       = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
_CIT_BRACKET_RE     = re.compile(r"\[[0-9,\- ]+\]")
_CIT_AUTH_YEAR_RE   = re.compile(
    r"\b[A-Z][a-zA-Z-]+(?:\s+and\s+[A-Z][a-zA-Z-]+)?\s*\((?:19|20)\d{2}\)"
)


def compute_semantic_micro(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute regex-based semantic markers for every block.

    Writes du_block_semantic_micro. Idempotent via INSERT OR REPLACE.
    """
    blocks = conn.execute(
        "SELECT block_id, text FROM du_blocks WHERE document_id = ? ORDER BY block_index",
        (document_id,),
    ).fetchall()
    if not blocks:
        return

    rows: list[tuple] = []
    for block in blocks:
        text = (block["text"] or "").strip()
        rows.append((
            block["block_id"],
            int(bool(_ABSTRACT_RE.search(text))),
            int(bool(_KEYWORDS_RE.search(text))),
            int(bool(_REFERENCES_RE.search(text))),
            int(bool(_FIGURE_RE.search(text))),
            int(bool(_TABLE_RE.search(text))),
            int(bool(_APPENDIX_RE.search(text))),
            int(bool(_DOI_RE.search(text))),
            int(bool(_YEAR_RE.search(text))),
            int(bool(_CIT_BRACKET_RE.search(text))),
            int(bool(_CIT_AUTH_YEAR_RE.search(text))),
            int(_contains_chapter_number(text)),
        ))

    conn.executemany(
        """
        INSERT INTO du_block_semantic_micro (
            block_id,
            is_abstract_marker, is_keywords_marker,
            is_references_marker,
            is_figure_marker, is_table_marker, is_appendix_marker,
            contains_doi, contains_year,
            contains_citation_bracket, contains_citation_author_year,
            contains_chapter_number
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            is_abstract_marker          = excluded.is_abstract_marker,
            is_keywords_marker          = excluded.is_keywords_marker,
            is_references_marker        = excluded.is_references_marker,
            is_figure_marker            = excluded.is_figure_marker,
            is_table_marker             = excluded.is_table_marker,
            is_appendix_marker          = excluded.is_appendix_marker,
            contains_doi                = excluded.contains_doi,
            contains_year               = excluded.contains_year,
            contains_citation_bracket   = excluded.contains_citation_bracket,
            contains_citation_author_year = excluded.contains_citation_author_year,
            contains_chapter_number     = excluded.contains_chapter_number
        """,
        rows,
    )
    conn.commit()
