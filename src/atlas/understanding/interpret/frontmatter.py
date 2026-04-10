# src/atlas/understanding/interpret/frontmatter.py
"""Dedicated interpretation of frontmatter blocks.

Frontmatter has a predictable, limited structure:
  - Title (most prominent block)
  - Subtitle (optional, directly after title, smaller)
  - Author(s)
  - Institution / affiliation
  - Date / year
  - Journal / publisher / series
  - Abstract (preceded by "Abstract" markword)
  - Keywords (preceded by "Keywords" markword)
  - DOI / ISSN / ISBN
  - Page furniture (headers, footers, logos)

Frontmatter does NOT contain:
  - Headings (section headings belong to body)
  - Body text (running prose belongs to body)
  - References

This module runs BEFORE roles.py for frontmatter blocks and assigns
roles directly based on prominence and position, not on signal scores.

Architecture
------------
Pass 3.0 — runs after zones.py, before headings.py:
  1. Fetch all blocks with zone = front_matter
  2. Identify title block (most prominent by font_size × visibility)
  3. Identify subtitle, authors, abstract, keywords
  4. Write role overrides into du_block_roles
  5. Headings in frontmatter are downgraded to title or titelei
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from atlas.core.logging import get_logger
from atlas.understanding.core.vocab import Role, Zone

_log = get_logger("atlas.du.frontmatter")


# ── Safe helpers ──────────────────────────────────────────────────────────────

def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d

def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v) if v is not None else d
    except (TypeError, ValueError):
        return d

def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()

def _wc(text: str) -> int:
    return len(text.split()) if text else 0


# ── Markword patterns ─────────────────────────────────────────────────────────

_ABSTRACT_MARKERS = {
    "abstract", "zusammenfassung", "résumé", "sommaire", "riassunto",
    "samenvatting", "resumen", "abtract",  # common typo
}

_KEYWORDS_MARKERS = {
    "keywords", "key words", "schlüsselwörter", "mots-clés", "mots clés",
    "parole chiave", "palabras clave",
}

_TITELEI_WORDS = {
    "contents", "inhalt", "inhaltsverzeichnis", "table of contents",
    "preface", "vorwort", "foreword", "acknowledgements", "danksagung",
    "list of figures", "list of tables", "abbreviations", "abkürzungen",
    "impressum", "copyright", "alle rechte vorbehalten", "all rights reserved",
    "published by", "printed by", "layout", "titelbild", "druck",
    "isbn", "issn", "doi",
}

def _is_abstract_marker(text: str) -> bool:
    return _norm(text).lower() in _ABSTRACT_MARKERS

def _is_keywords_marker(text: str) -> bool:
    return _norm(text).lower() in _KEYWORDS_MARKERS

def _is_titelei(text: str) -> bool:
    t = _norm(text).lower()
    return any(t.startswith(w) or t == w for w in _TITELEI_WORDS)

def _looks_like_author(text: str) -> bool:
    """Heuristic: author lines are short, no sentence structure."""
    t = _norm(text)
    wc = _wc(t)
    if wc < 1 or wc > 8:
        return False
    if t.endswith(".") or t.endswith(":"):
        return False
    # Contains comma-separated names or "and"/"und"
    if re.search(r'\band\b|\bund\b|\bvon\b|\band\b', t, re.IGNORECASE):
        return True
    # Starts with "by " or "von "
    if re.match(r'^(by|von)\s', t, re.IGNORECASE):
        return True
    return False


# ── Database access ───────────────────────────────────────────────────────────

def _fetch_frontmatter_blocks(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[dict]:
    """Fetch all blocks in the frontmatter zone with their signals."""
    rows = conn.execute(
        """
        SELECT
            b.block_id, b.block_index, b.page_index, b.text,
            COALESCE(t.font_size, 0.0)          AS font_size,
            COALESCE(t.bold, 0)                 AS bold,
            COALESCE(t.italic, 0)               AS italic,
            COALESCE(t.is_letter_spaced, 0)     AS is_letter_spaced,
            COALESCE(sf.word_count, 0)          AS word_count,
            COALESCE(sf.char_count, 0)          AS char_count,
            COALESCE(sf.is_all_caps, 0)         AS is_all_caps,
            COALESCE(sf.ends_with_period, 0)    AS ends_with_period,
            COALESCE(g.doc_y_ratio, 0.0)        AS doc_y_ratio,
            COALESCE(g.centeredness, 0.5)       AS centeredness,
            COALESCE(f.running_header_like, 0)  AS running_header_like,
            COALESCE(f.repeated_across_pages, 0) AS repeated_across_pages,
            r.role                              AS current_role,
            COALESCE(r.title_score, 0.0)        AS title_score,
            COALESCE(r.author_score, 0.0)       AS author_score,
            COALESCE(r.noise_score, 0.0)        AS noise_score
        FROM du_blocks b
        LEFT JOIN du_block_typography    t  ON t.block_id  = b.block_id
        LEFT JOIN du_block_surface       sf ON sf.block_id = b.block_id
        LEFT JOIN du_block_geometry      g  ON g.block_id  = b.block_id
        LEFT JOIN du_block_furniture     f  ON f.block_id  = b.block_id
        LEFT JOIN du_block_zones         z  ON z.block_id  = b.block_id
        LEFT JOIN du_block_roles         r  ON r.block_id  = b.block_id
        WHERE b.document_id = ?
        AND z.zone IN (?, ?)
        ORDER BY b.block_index
        """,
        (document_id, Zone.FRONT_MATTER, Zone.TITLE_PAGE),
    ).fetchall()
    return [dict(r) for r in rows]


def _update_role(
    conn: sqlite3.Connection,
    block_id: str,
    role: str,
) -> None:
    conn.execute(
        "UPDATE du_block_roles SET role = ? WHERE block_id = ?",
        (role, block_id),
    )


# ── Prominence score ──────────────────────────────────────────────────────────

def _prominence(block: dict) -> float:
    """Score for how prominent a block is as a title candidate.

    Combines font size, character count, and position.
    Large, early, centered blocks score highest.
    """
    fs      = _f(block.get("font_size"))
    chars   = _i(block.get("char_count"))
    y_ratio = _f(block.get("doc_y_ratio"), 1.0)
    center  = _f(block.get("centeredness"), 0.5)
    wc      = _i(block.get("word_count"))

    # Filter artefacts: font_size > 100pt is a PDF artefact
    # (symbol font, vector graphic text, etc.)
    if fs <= 0 or fs > 100.0 or chars <= 0 or wc < 2:
        return 0.0

    # Furniture is never title
    if block.get("running_header_like") or block.get("repeated_across_pages"):
        return 0.0

    # Titelei words are never title
    text = _norm(block.get("text"))
    if _is_titelei(text):
        return 0.0

    # Very long blocks (>20 words) are body/abstract, not title
    if wc > 20:
        return 0.0

    # Score: font_size is the PRIMARY signal.
    # Larger font = more prominent, regardless of text length.
    # char_count is a tiebreaker only — avoids single-char artefacts.
    # Earlier and centered blocks get a small bonus.
    position_bonus = max(0.0, 1.0 - y_ratio * 3.0)
    center_bonus   = max(0.0, 1.0 - _f(center) * 2.0)
    # Normalize char_count: full bonus at ≥10 chars, zero at 0
    char_bonus = min(1.0, chars / 10.0)
    score = fs * (1.0 + position_bonus * 0.3 + center_bonus * 0.2 + char_bonus * 0.1)
    return score


# ── Public API ────────────────────────────────────────────────────────────────

def interpret_frontmatter(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Interpret frontmatter blocks and assign roles.

    Returns the detected title text, or None.

    Algorithm:
    1. Fetch all frontmatter blocks
    2. Skip furniture
    3. Find title = most prominent block
    4. Find subtitle = next most prominent, directly after title
    5. Find authors = blocks matching author heuristic near title
    6. Find abstract = block after abstract markword
    7. Everything else → titelei (body/noise)
    8. Downgrade any heading role to title or titelei

    Writes role updates to du_block_roles.
    Idempotent — can be called multiple times.
    """
    blocks = _fetch_frontmatter_blocks(conn, document_id)
    if not blocks:
        _log.debug("frontmatter doc=%s: no frontmatter blocks", document_id[:12])
        return None

    _log.debug(
        "frontmatter doc=%s: %d blocks in frontmatter",
        document_id[:12], len(blocks),
    )

    # ── Step 1: Find title block ──────────────────────────────────────────────
    # Title = highest prominence score, wc ≤ 18
    scored = [(b, _prominence(b)) for b in blocks]
    scored.sort(key=lambda x: -x[1])

    title_block = None
    title_idx   = None

    for b, score in scored:
        if score <= 0:
            continue
        wc = _i(b.get("word_count"))
        if wc < 2 or wc > 18:
            continue
        title_block = b
        title_idx   = _i(b.get("block_index"))
        break

    if title_block is None:
        _log.debug("frontmatter doc=%s: no title block found", document_id[:12])
        # Still downgrade any misclassified headings
        _downgrade_frontmatter_headings(conn, blocks)
        conn.commit()
        return None

    title_text = _norm(title_block.get("text"))
    _log.info(
        "frontmatter doc=%s: title='%s' (fs=%.1f)",
        document_id[:12], title_text[:50],
        _f(title_block.get("font_size")),
    )

    # Mark title block
    _update_role(conn, title_block["block_id"], Role.TITLE)

    # ── Step 2: Subtitle intentionally disabled ─────────────────────────────
    # Subtitle detection causes more harm than good — it incorrectly
    # merges chapter headings and running titles into the document title.
    # Only the single most prominent block is marked as title.
    title_fs = _f(title_block.get("font_size"))

    # ── Step 3: Assign authors ────────────────────────────────────────────────
    for b in blocks:
        if b["block_id"] == title_block["block_id"]:
            continue
        role = b.get("current_role") or ""
        if role == Role.AUTHOR:
            continue  # already assigned
        author_score = _f(b.get("author_score"))
        text = _norm(b.get("text"))
        wc   = _i(b.get("word_count"))
        if author_score >= 0.6 and wc <= 8:
            _update_role(conn, b["block_id"], Role.AUTHOR)
        elif _looks_like_author(text) and _i(b.get("block_index")) < title_idx + 20:
            _update_role(conn, b["block_id"], Role.AUTHOR)

    # ── Step 4: Downgrade misclassified headings ──────────────────────────────
    _downgrade_frontmatter_headings(conn, blocks, title_block["block_id"])

    conn.commit()
    return title_text


def _downgrade_frontmatter_headings(
    conn: sqlite3.Connection,
    blocks: list[dict],
    title_block_id: str | None = None,
) -> None:
    """Downgrade heading roles in frontmatter to body/titelei.

    Headings do not exist in frontmatter. Any block classified as
    heading in the frontmatter zone is either:
    - A misclassified title → already handled above
    - A titelei element (TOC header, series title) → body
    """
    for b in blocks:
        if b["block_id"] == title_block_id:
            continue
        role = b.get("current_role") or ""
        if role == Role.HEADING:
            text = _norm(b.get("text"))
            _update_role(conn, b["block_id"], Role.BODY)
            _log.debug(
                "frontmatter doc: downgraded heading→body: %s",
                text[:40],
            )
