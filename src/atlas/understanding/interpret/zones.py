# src/atlas/understanding/interpret/zones.py
"""Layer 3 — assign semantic zones to blocks.

Detects front-matter, body, and back-matter boundaries using
block-level evidence signals, then writes one zone per block
to du_block_zones.

Zone names come from vocab.Zone. The old "front"/"body"/"back"
strings are gone.

Fields affiliation_like / date_like / journal_meta_like are not
in the schema — their contributions are approximated via
author_like, first_page_meta_like, and front_matter_score.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from atlas.core.logging import get_logger
_log = get_logger("atlas.du.zones")

from atlas.understanding.core.vocab import Zone
from atlas.understanding.core.section_labels import ALL_BACK_MATTER_HEADINGS
from atlas.understanding.core.text_patterns import (
    contains_chapter_number,
    normalize_lower,
)
from atlas.understanding.core.section_labels import (
    ABSTRACT_HEADINGS,
    REFERENCE_HEADINGS,
)

# Explicit headings that mark unambiguous body-start (not numbered).
# "Introduction" alone is borderline — only used for article/archival.
_INTRODUCTION_HEADINGS: frozenset[str] = frozenset({
    # English
    "introduction", "preface", "foreword",
    # German
    "einleitung", "vorwort",
    # French
    "introduction", "préface", "avant-propos",
    # Spanish
    "introducción", "prefacio",
    # Dutch
    "inleiding", "voorwoord",
})


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

def _b(v: Any) -> bool:
    return bool(v)

def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


# ── Database read ─────────────────────────────────────────────────────────────

def _fetch_blocks(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """
        SELECT b.block_id, b.block_index, b.text,
               g.doc_y_ratio, g.page_y_ratio, g.centeredness,
               t.font_size,
               s.title_like, s.author_like, s.body_like,
               s.reference_like, s.caption_like, s.heading_like,
               r.heading_score, r.body_score, r.reference_score, r.caption_score,
               sf.word_count, sf.sentence_count,
               sf.digit_density, sf.punctuation_density,
               sf.is_short_line,
               sm.is_references_marker, sm.is_appendix_marker,
               sm.contains_citation_author_year, sm.contains_citation_bracket,
               sm.contains_year,
               sm.contains_chapter_number,
               ctx.front_matter_score, ctx.back_matter_score,
               f.running_header_like, f.repeated_across_pages,
               f.first_page_meta_like,
               t2.italic
        FROM du_blocks b
        LEFT JOIN du_block_geometry      g   ON g.block_id  = b.block_id
        LEFT JOIN du_block_typography    t   ON t.block_id  = b.block_id
        LEFT JOIN du_block_typography    t2  ON t2.block_id = b.block_id
        LEFT JOIN du_block_signals       s   ON s.block_id  = b.block_id
        LEFT JOIN du_block_roles         r   ON r.block_id  = b.block_id
        LEFT JOIN du_block_surface       sf  ON sf.block_id = b.block_id
        LEFT JOIN du_block_semantic_micro sm ON sm.block_id = b.block_id
        LEFT JOIN du_block_context       ctx ON ctx.block_id = b.block_id
        LEFT JOIN du_block_furniture     f   ON f.block_id  = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()]


# ── Evidence signals ──────────────────────────────────────────────────────────

def _front_signal(block: dict, body_font: float) -> float:
    text = _norm(block.get("text"))
    if not text:
        return 0.0

    ref_s = _f(block.get("reference_score"))
    cap_s = _f(block.get("caption_score"))
    if ref_s > 0.4 or cap_s > 0.4:
        return 0.0
    if _b(block.get("is_references_marker")):
        return 0.0

    score = 0.0
    doc_y    = _f(block.get("doc_y_ratio"), 1.0)
    page_y   = _f(block.get("page_y_ratio"), 1.0)
    front_s  = _f(block.get("front_matter_score"))
    title_l  = _f(block.get("title_like"))
    author_l = _f(block.get("author_like"))
    fp_meta  = _f(block.get("first_page_meta_like"))
    center   = _f(block.get("centeredness"))
    font_s   = _f(block.get("font_size"))
    body_s   = _f(block.get("body_score"))
    head_s   = _f(block.get("heading_score"))

    if doc_y <= 0.18:    score += 0.35
    if page_y <= 0.22:   score += 0.15
    score += 0.35 * min(front_s,  1.0)
    score += 0.30 * min(title_l,  1.0)
    score += 0.25 * min(author_l, 1.0)
    score += 0.20 * min(fp_meta,  1.0)
    if center >= 0.55:   score += 0.15
    if font_s >= body_font + 1.0: score += 0.15
    if _b(block.get("running_header_like")) or _b(block.get("repeated_across_pages")):
        score += 0.10
    if body_s > head_s and len(text.split()) >= 12:
        score -= 0.25

    return max(0.0, min(1.0, score))


def _body_signal(block: dict, body_font: float) -> float:
    text = _norm(block.get("text"))
    if not text:
        return 0.0

    score  = 0.0
    body_s = _f(block.get("body_like"))
    ctx_b  = _f(block.get("body_score"))
    head_s = _f(block.get("heading_score"))
    front  = _f(block.get("front_matter_score"))
    back   = _f(block.get("back_matter_score"))
    ref_s  = _f(block.get("reference_score"))
    cap_s  = _f(block.get("caption_score"))
    wc     = _i(block.get("word_count"))
    sc     = _i(block.get("sentence_count"))
    page_y = _f(block.get("page_y_ratio"), 0.5)
    font_s = _f(block.get("font_size"))

    score += 0.45 * min(body_s, 1.0)
    score += 0.35 * min(ctx_b,  1.0)
    if wc >= 10:                              score += 0.15
    if sc >= 1:                               score += 0.10
    if 0.10 <= page_y <= 0.90:               score += 0.10
    if abs(font_s - body_font) <= 1.0:       score += 0.10
    score -= 0.20 * min(front, 1.0)
    score -= 0.20 * min(back,  1.0)
    score -= 0.25 * min(ref_s, 1.0)
    score -= 0.15 * min(cap_s, 1.0)
    if head_s > body_s and wc <= 6:          score += 0.05

    return max(0.0, min(1.0, score))


def _back_signal(block: dict, total: int) -> float:
    text = _norm(block.get("text"))
    if not text:
        return 0.0

    score  = 0.0
    idx    = _i(block.get("block_index"))
    back_s = _f(block.get("back_matter_score"))
    ref_s  = _f(block.get("reference_score"))
    wc     = _i(block.get("word_count"))
    frac   = idx / max(total - 1, 1)

    if frac >= 0.75: score += 0.20
    if frac >= 0.85: score += 0.20
    score += 0.35 * min(back_s, 1.0)
    score += 0.35 * min(ref_s,  1.0)

    if _b(block.get("is_references_marker")): score += 0.50
    if _b(block.get("is_appendix_marker")):   score += 0.50
    if any(k in text for k in ALL_BACK_MATTER_HEADINGS):    score += 0.40
    if _b(block.get("contains_citation_author_year")) or \
       _b(block.get("contains_citation_bracket")):     score += 0.15
    if _b(block.get("contains_year")) and wc >= 4:     score += 0.10
    if _f(block.get("digit_density")) >= 0.08:         score += 0.05
    if _f(block.get("punctuation_density")) >= 0.08:   score += 0.05
    if _b(block.get("italic")) and wc >= 6:            score += 0.05

    return max(0.0, min(1.0, score))


# ── Boundary detection ────────────────────────────────────────────────────────

def _is_explicit_body_anchor(block: dict, doc_type: str | None) -> bool:
    """True if this block is an unambiguous body-start marker.

    Two tiers:
    - Tier 1 (all doc types): numbered heading like '1 Introduction',
      '1.1 Materials', 'Chapter 1'. Reliable across all document types.
    - Tier 2 (article/archival only): unnumbered introduction/preface
      heading. Reliable for articles; too aggressive for monographs
      where a Preface is still Frontmatter.
    - Abstract heading: marks end of Frontmatter for articles.
      The abstract block itself is included in body_start.
    """
    text = _norm(block.get("text"))
    if not text:
        return False

    # Furniture blocks are never anchors
    if _b(block.get("running_header_like")) or _b(block.get("repeated_across_pages")):
        return False

    # Tier 1 — numbered heading (all doc types)
    # contains_chapter_number already stored in du_block_semantic_micro
    if _b(block.get("contains_chapter_number")):
        return True

    text_norm = normalize_lower(block.get("text"))

    # Tier 1b — abstract heading (all doc types)
    # Abstract is the last Frontmatter element for articles,
    # and a reliable anchor in monographs too.
    if text_norm in ABSTRACT_HEADINGS:
        return True

    # Tier 2 — unnumbered introduction/preface (article/archival only)
    if doc_type in ("article", "archival"):
        if text_norm in _INTRODUCTION_HEADINGS:
            return True

    return False


def _is_qualified_body_block(block: dict, body_font: float) -> bool:
    """True if this block looks like substantive body text.

    Stricter than _body_signal >= threshold: requires meaningful
    word count to exclude captions, headings, and isolated lines
    that can score high on body_signal despite being Frontmatter.
    """
    wc = _i(block.get("word_count"))
    if wc < 8:
        return False
    # Furniture never qualifies
    if _b(block.get("running_header_like")) or _b(block.get("repeated_across_pages")):
        return False
    return _body_signal(block, body_font) >= 0.55


def _detect_body_start(
    blocks: list[dict],
    body_font: float,
    doc_type: str | None = None,
) -> int:
    """Detect where body content begins.

    Strategy (in priority order):

    1. Explicit anchor — a numbered heading or named section marker
       is an unambiguous body-start signal. No fuzzy logic needed.
       Searched within early_limit.

    2. Qualified body-run — N consecutive blocks that are substantive
       body text (word_count >= 8, body_signal >= 0.55). The run
       requirement prevents isolated Frontmatter paragraphs from
       triggering a premature body_start.

    3. Fallback — last block with strong front_signal + 1.
       For articles with no detectable Frontmatter at all,
       body_start = 0 (whole document is body).

    Parameters are tuned by document type:
    - article/archival: short frontmatter, lower early_limit
    - monograph/thesis: long frontmatter allowed
    - report or unknown: medium
    """
    n = len(blocks)

    if doc_type in ("article", "archival"):
        N_BODY_RUN  = 4
        early_limit = max(15, int(n * 0.15))
    elif doc_type in ("monograph", "thesis"):
        N_BODY_RUN  = 3
        early_limit = max(60, int(n * 0.25))
    else:
        N_BODY_RUN  = 3
        early_limit = max(40, int(n * 0.20))

    # ── Pass 1: explicit anchors ──────────────────────────────────────────────
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx > early_limit:
            break
        if _is_explicit_body_anchor(block, doc_type):
            _log.debug(
                "body_start: explicit anchor at block %d: %r",
                idx, (block.get("text") or "")[:60],
            )
            return idx

    # ── Pass 2: qualified body-run ────────────────────────────────────────────
    run = 0
    first_body_idx = -1

    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx > early_limit:
            break
        if _is_qualified_body_block(block, body_font):
            if run == 0:
                first_body_idx = idx
            run += 1
            if run >= N_BODY_RUN:
                _log.debug(
                    "body_start: qualified body run at block %d", first_body_idx
                )
                return first_body_idx
        else:
            run = 0
            first_body_idx = -1

    # ── Pass 3: fallback ──────────────────────────────────────────────────────
    # For articles: if nothing found, assume body starts at block 0.
    # Articles typically have no meaningful Frontmatter — the "Frontmatter"
    # is just a page header that repeated_across_pages handles.
    if doc_type in ("article", "archival"):
        _log.debug("body_start: article fallback → 0")
        return 0

    # For other types: last block with strong front_signal + 1.
    last_front = -1
    for block in blocks[:early_limit]:
        idx = _i(block.get("block_index"))
        if _front_signal(block, body_font) >= 0.45:
            last_front = idx
    result = max(0, last_front + 1)
    _log.debug("body_start: front-signal fallback → %d", result)
    return result


def _detect_back_start(blocks: list[dict], total: int, body_font: float) -> int | None:
    """Detect where back-matter begins.

    Strategy: find the *first* block after the 65% threshold that has
    a strong back_signal AND is confirmed by at least one of the
    following N blocks also scoring >= 0.40. This prevents a single
    citation-heavy body block from triggering an early back_start.

    The old argmax approach selected the globally highest-scoring block,
    which could be deep in the body (e.g. Yeomans: back_matter:20489).
    """
    HARD_THRESHOLD  = int(total * 0.65)
    STRONG_SCORE    = 0.55
    CONFIRM_SCORE   = 0.40
    CONFIRM_WINDOW  = 4   # look ahead N blocks for confirmation

    # Build index → block map for lookahead
    by_idx = {_i(b.get("block_index")): b for b in blocks}

    candidates: list[tuple[int, float]] = []  # (block_index, score)
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx < HARD_THRESHOLD:
            continue
        score = _back_signal(block, total)
        if score >= STRONG_SCORE:
            candidates.append((idx, score))

    for idx, score in candidates:
        # Require at least one confirming block in the next CONFIRM_WINDOW blocks
        confirmed = False
        for offset in range(1, CONFIRM_WINDOW + 1):
            neighbor = by_idx.get(idx + offset)
            if neighbor is None:
                continue
            # Confirming block: either also back-matter, or a furniture block
            # (page furniture at end of document doesn't invalidate the signal)
            if (_back_signal(neighbor, total) >= CONFIRM_SCORE
                    or _b(neighbor.get("running_header_like"))
                    or _b(neighbor.get("repeated_across_pages"))):
                confirmed = True
                break
        if confirmed:
            _log.debug("back_start: confirmed at block %d (score=%.2f)", idx, score)
            return idx

    # Soft fallback: first strong signal without confirmation requirement
    # (covers short documents where the lookahead window runs out)
    fallback_start = int(total * 0.85)
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx >= fallback_start and _back_signal(block, total) >= STRONG_SCORE:
            _log.debug("back_start: fallback at block %d", idx)
            return idx

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def compute_zones(conn: sqlite3.Connection, document_id: str) -> None:
    """Assign a zone to every block of one document.

    Writes du_block_zones. Idempotent — DELETE + INSERT.
    """
    blocks = _fetch_blocks(conn, document_id)
    if not blocks:
        return

    font_sizes = sorted(_f(b.get("font_size")) for b in blocks if b.get("font_size"))
    body_font  = font_sizes[len(font_sizes) // 2] if font_sizes else 10.0
    total      = len(blocks)

    _dt = conn.execute(
        "SELECT du_document_type FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    doc_type = _dt["du_document_type"] if _dt else None
    _log.debug("zones doc=%s: doc_type=%s", document_id[:12], doc_type)

    body_start = _detect_body_start(blocks, body_font, doc_type=doc_type)
    back_start = _detect_back_start(blocks, total, body_font)

    if back_start is not None and back_start <= body_start:
        back_start = None

    _log.debug(
        "zones doc=%s: total=%d body_font=%.1f body_start=%d back_start=%s",
        document_id[:12], total, body_font, body_start, back_start,
    )

    # Build block_index → zone mapping
    zone_map: dict[int, str] = {}
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx < body_start:
            zone_map[idx] = Zone.FRONT_MATTER
        elif back_start is not None and idx >= back_start:
            zone_map[idx] = Zone.BACK_MATTER
        else:
            zone_map[idx] = Zone.BODY

    conn.execute(
        "DELETE FROM du_block_zones WHERE block_id IN "
        "(SELECT block_id FROM du_blocks WHERE document_id = ?)",
        (document_id,),
    )

    rows: list[tuple] = []
    for block in blocks:
        idx  = _i(block.get("block_index"))
        zone = zone_map[idx]
        fs   = _front_signal(block, body_font)
        bs   = _body_signal(block, body_font)
        bk   = _back_signal(block, total)
        memberships = json.dumps({
            Zone.FRONT_MATTER: round(fs, 3),
            Zone.BODY:         round(bs, 3),
            Zone.BACK_MATTER:  round(bk, 3),
        })
        conf = max(fs, bs, bk)
        rows.append((block["block_id"], zone, round(conf, 3), memberships))

    conn.executemany(
        """
        INSERT INTO du_block_zones (block_id, zone, zone_confidence, memberships)
        VALUES (?,?,?,?)
        """,
        rows,
    )
    conn.commit()
