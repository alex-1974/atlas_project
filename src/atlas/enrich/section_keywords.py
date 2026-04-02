# src/atlas/enrich/section_keywords.py
"""Per-section keyword extraction.

Why section-level keywords?
----------------------------
Document-level keywords aggregate over all chapters and lose
chapter-specific terms. A chapter on roof construction in a
timber manual will not surface 'Dach' as a document keyword —
but it is the most important term for that chapter.

Approach
--------
For each section in du_section_tree:
    1. Collect all body blocks belonging to this section
       (block_index between start_block_index and end_block_index)
    2. Concatenate block texts
    3. Run YAKE (fast, no model needed) on the section text
    4. Store in du_section_keywords

For very short sections (< 30 words), the section title itself
is used as the only keyword — no extraction needed.

Sliding window option
---------------------
For long sections (> 500 words), extraction runs on the full
section text. A sliding window within sections is not yet
implemented — the section boundary already provides the
necessary granularity for most documents.

Stored in: du_section_keywords
"""
from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger(__name__)

_MIN_WORDS_FOR_EXTRACTION = 30
_MAX_KEYWORDS_PER_SECTION = 6


# ── Public API ────────────────────────────────────────────────────────────────

def extract_section_keywords(
    conn: sqlite3.Connection,
    document_id: str,
    method: str = "yake",
    force: bool = False,
) -> dict[int, list[str]]:
    """Extract and store keywords for each section of a document.

    Returns {section_node_id: [keywords]} dict.
    """
    # Check if already done
    if not force:
        existing = conn.execute(
            "SELECT COUNT(*) FROM du_section_keywords WHERE document_id = ?",
            (document_id,),
        ).fetchone()[0]
        if existing > 0:
            return _load_section_keywords(conn, document_id)

    sections = _load_sections(conn, document_id)
    if not sections:
        return {}

    results: dict[int, list[str]] = {}

    for section in sections:
        node_id = section["section_node_id"]
        text    = _get_section_text(conn, document_id, section)

        if not text or len(text.split()) < _MIN_WORDS_FOR_EXTRACTION:
            # Short section: use title as keyword
            title = (section["title"] or "").strip()
            keywords = [title] if title else []
        elif method == "yake":
            keywords = _extract_yake(text, section["title"])
        else:
            keywords = _extract_tfidf_fallback(text)

        keywords = _clean_keywords(keywords)
        results[node_id] = keywords

        _write_section_keywords(conn, document_id, node_id, keywords, method)

    return results


def section_keywords_for_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> dict[int, list[str]]:
    """Return stored section keywords, extracting if not present."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM du_section_keywords WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    if existing > 0:
        return _load_section_keywords(conn, document_id)
    return extract_section_keywords(conn, document_id)


# ── Text collection ───────────────────────────────────────────────────────────

def _load_sections(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[sqlite3.Row]:
    """Load all sections for a document."""
    return conn.execute(
        """
        SELECT section_node_id, title, level,
               start_block_index, end_block_index
        FROM du_section_tree
        WHERE document_id = ?
        ORDER BY start_block_index
        """,
        (document_id,),
    ).fetchall()


def _get_section_text(
    conn: sqlite3.Connection,
    document_id: str,
    section: sqlite3.Row,
) -> str:
    """Collect body block texts for a section."""
    start = section["start_block_index"]
    end   = section["end_block_index"]

    if start is None or end is None:
        return ""

    rows = conn.execute(
        """
        SELECT b.text FROM du_blocks b
        JOIN du_block_roles r ON r.block_id = b.block_id
        WHERE b.document_id = ?
          AND b.block_index >= ?
          AND b.block_index <= ?
          AND r.role IN ('body', 'heading', 'caption')
        ORDER BY b.block_index
        LIMIT 100
        """,
        (document_id, start, end),
    ).fetchall()

    return " ".join((r["text"] or "").strip() for r in rows if r["text"])


# ── Extraction methods ────────────────────────────────────────────────────────

def _extract_yake(text: str, section_title: str | None) -> list[str]:
    """Extract keywords using YAKE."""
    try:
        import yake as _yake
    except ImportError:
        log.debug("yake not installed — falling back to TF-IDF for sections")
        return _extract_tfidf_fallback(text)

    # Weight section title by prepending it 3x
    weighted_text = text
    if section_title:
        weighted_text = (section_title + " ") * 3 + text

    kw_extractor = _yake.KeywordExtractor(
        lan="en",         # YAKE handles DE too without explicit lang
        n=2,              # bigrams only — avoids phantom repetitions
        dedupLim=0.4,     # aggressive deduplication
        dedupFunc="seqm",
        windowsSize=2,
        top=_MAX_KEYWORDS_PER_SECTION * 2,
        features=None,
    )

    try:
        raw = kw_extractor.extract_keywords(weighted_text)
        # YAKE: lower score = more relevant
        return [kw for kw, score in raw if score <= 0.35]
    except Exception as exc:
        log.debug("YAKE section extraction failed: %s", exc)
        return []


def _extract_tfidf_fallback(text: str) -> list[str]:
    """Simple frequency-based fallback."""
    import re
    from collections import Counter

    _STOPWORDS = {
        "the", "a", "an", "and", "or", "of", "in", "on", "at", "to",
        "for", "with", "by", "from", "as", "is", "are", "was", "were",
        "its", "their", "this", "that", "these", "those", "some",
        "der", "die", "das", "des", "dem", "den", "ein", "eine",
        "und", "oder", "von", "zu", "im", "am", "auf", "an", "mit",
        "aus", "für", "über", "nach", "bei",
    }

    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{5,}\b', text.lower())
    filtered = [w for w in words if w not in _STOPWORDS]
    counts = Counter(filtered)
    return [w for w, _ in counts.most_common(_MAX_KEYWORDS_PER_SECTION * 2)]


# ── Cleaning ──────────────────────────────────────────────────────────────────

def _clean_keywords(keywords: list[str]) -> list[str]:
    """Normalise and deduplicate section keywords."""
    import string
    _STRIP = string.punctuation + '…"„"\u2018\u2019\u2014\u2013'

    _NOISE = {
        "figure", "table", "section", "chapter", "reference", "references",
        "figure", "abbildung", "tabelle", "abschnitt", "kapitel",
    }

    cleaned = []
    seen_lower: set[str] = set()

    for kw in keywords:
        kw = kw.strip(_STRIP).strip()
        kw = " ".join(kw.split())
        if len(kw) < 4:
            continue
        if kw.lower() in _NOISE:
            continue
        lower = kw.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        cleaned.append(kw)

    # Prefer multi-word, then single words ≥ 6 chars
    multi  = [k for k in cleaned if len(k.split()) >= 2]
    single = [k for k in cleaned if len(k.split()) == 1 and len(k) >= 6]
    return (multi + single)[:_MAX_KEYWORDS_PER_SECTION]


# ── Database I/O ──────────────────────────────────────────────────────────────

def _write_section_keywords(
    conn: sqlite3.Connection,
    document_id: str,
    section_node_id: int,
    keywords: list[str],
    method: str,
) -> None:
    conn.execute(
        """
        INSERT INTO du_section_keywords
            (section_node_id, document_id, keywords, keyword_method)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(section_node_id) DO UPDATE
            SET keywords = excluded.keywords,
                keyword_method = excluded.keyword_method,
                extracted_at = datetime('now')
        """,
        (section_node_id, document_id,
         json.dumps(keywords, ensure_ascii=False), method),
    )
    conn.commit()


def _load_section_keywords(
    conn: sqlite3.Connection,
    document_id: str,
) -> dict[int, list[str]]:
    rows = conn.execute(
        "SELECT section_node_id, keywords FROM du_section_keywords "
        "WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    result = {}
    for row in rows:
        try:
            result[row["section_node_id"]] = json.loads(row["keywords"])
        except (json.JSONDecodeError, TypeError):
            result[row["section_node_id"]] = []
    return result
