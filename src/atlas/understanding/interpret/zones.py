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

from atlas.understanding.core.vocab import Zone
from atlas.understanding.core.section_labels import ALL_BACK_MATTER_HEADINGS


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
    # first_page_meta_like approximates affiliation/date/journal_meta
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
    score += 0.20 * min(fp_meta,  1.0)   # covers affiliation/journal_meta
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
    body_s = _f(block.get("body_like"))    # signal score (layer 2)
    # context body_score approximates old context_body_score
    ctx_b  = _f(block.get("body_score"))   # role score (layer 3)
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

def _detect_body_start(blocks: list[dict], body_font: float) -> int:
    last_front, seen_body = -1, False
    early_limit = max(30, int(len(blocks) * 0.25))
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx > early_limit and seen_body:
            break
        if _front_signal(block, body_font) >= 0.45:
            last_front = idx
        if _body_signal(block, body_font) >= 0.55:
            seen_body = True
    return max(0, last_front + 1)


def _detect_back_start(blocks: list[dict], total: int) -> int | None:
    threshold = int(total * 0.65)
    best_idx, best_score = None, 0.0
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx < threshold:
            continue
        score = _back_signal(block, total)
        if score > best_score and score >= 0.55:
            best_score, best_idx = score, idx
    if best_idx is not None:
        return best_idx
    fallback = int(total * 0.85)
    for block in blocks:
        idx = _i(block.get("block_index"))
        if idx >= fallback and _back_signal(block, total) >= 0.40:
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

    body_start = _detect_body_start(blocks, body_font)
    back_start = _detect_back_start(blocks, total)
    if back_start is not None and back_start <= body_start:
        back_start = None

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

    # Compute soft memberships for debugging (stored as JSON)
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
