# src/atlas/understanding/interpret/headings.py
"""Layer 3 — collect and normalise heading candidates.

Two-step pipeline:
  1. collect_heading_candidates   — score-based + typographic + expansion signals
  2. normalize_headings           — filter junk, merge multi-line titles

Zone names come from vocab.Zone. The old "front"/"body"/"back" strings
are replaced with Zone.FRONT_MATTER / Zone.BODY / Zone.BACK_MATTER.

Note: store_document_model is not called — the new schema has no
document_model table. Style clustering belongs to section_tree.py.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from atlas.understanding.core.vocab import Zone
from atlas.understanding.core.text_patterns import (
    is_reference_heading, is_appendix_heading, is_caption_like,
    is_author_line, is_author_bio, is_contact_line, is_meta_line,
    is_reference_entry, is_fragment_heading, is_sentence_heading,
    is_formula_label, normalize_letter_spaced,
    normalize,
)


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


# ── Zone name mapping from old → new ─────────────────────────────────────────

_OLD_TO_NEW = {
    "front":  Zone.FRONT_MATTER,
    "body":   Zone.BODY,
    "back":   Zone.BACK_MATTER,
    # already-new names pass through
    Zone.FRONT_MATTER: Zone.FRONT_MATTER,
    Zone.BODY:         Zone.BODY,
    Zone.BACK_MATTER:  Zone.BACK_MATTER,
    Zone.REFERENCES:   Zone.BACK_MATTER,
    Zone.APPENDIX:     Zone.BACK_MATTER,
    Zone.TITLE_PAGE:   Zone.FRONT_MATTER,
    Zone.ABSTRACT:     Zone.FRONT_MATTER,
}


# ── Database read ─────────────────────────────────────────────────────────────

def _fetch_blocks(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """
        SELECT b.block_id, b.block_index, b.page_index, b.text,
               t.font_size, t.italic, t.bold,
               COALESCE(t.font_percentile, 0.5) AS font_percentile,
               COALESCE(t.is_letter_spaced, 0)  AS is_letter_spaced,
               s.title_like, s.heading_like, s.body_like,
               s.caption_like, s.noise_like, s.reference_like,
               r.role, r.title_score, r.heading_score, r.body_score,
               r.caption_score, r.noise_score, r.reference_score,
               sf.word_count, sf.is_short_line,
               COALESCE(g.narrow_width_like, 0) AS narrow_width_like,
               COALESCE(g.near_image_score,  0) AS near_image_score,
               sm.is_references_marker, sm.is_appendix_marker,
               sm.is_figure_marker, sm.is_table_marker,
               sm.contains_doi,
               z.zone
        FROM du_blocks b
        LEFT JOIN du_block_typography    t  ON t.block_id  = b.block_id
        LEFT JOIN du_block_signals       s  ON s.block_id  = b.block_id
        LEFT JOIN du_block_roles         r  ON r.block_id  = b.block_id
        LEFT JOIN du_block_surface       sf ON sf.block_id = b.block_id
        LEFT JOIN du_block_geometry      g  ON g.block_id  = b.block_id
        LEFT JOIN du_block_semantic_micro sm ON sm.block_id = b.block_id
        LEFT JOIN du_block_zones         z  ON z.block_id  = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.page_index, b.block_index
        """,
        (document_id,),
    ).fetchall()]


# ── Zone-aware score adjustment ───────────────────────────────────────────────

def _adjust_heading_score(block: dict, zone: str) -> float:
    h = _f(block.get("heading_score"))
    b = _f(block.get("body_score"))
    n = _f(block.get("noise_score"))
    c = _f(block.get("caption_score"))
    r = _f(block.get("reference_score"))

    text       = normalize(block.get("text")).lower()
    font_size  = _f(block.get("font_size"))
    italic     = bool(block.get("italic"))
    title_s    = _f(block.get("title_score"))
    wc         = _i(block.get("word_count"))

    if block.get("is_figure_marker") or block.get("is_table_marker"):  h *= 0.25
    if c >= 0.45:  h *= 0.35
    if n >= 0.45:  h *= 0.50
    if block.get("contains_doi"):  h *= 0.50

    if zone == Zone.FRONT_MATTER:
        if title_s >= 0.5 and font_size >= 14.0:  h *= 0.25
        elif wc >= 8:                              h *= 0.65
        else:                                      h *= 0.85

    elif zone == Zone.BODY:
        if h > b:                                  h *= 1.05
        if italic and 1 <= wc <= 6:                h *= 1.05

    elif zone == Zone.BACK_MATTER:
        anchor_kws = ("reference", "bibliograph", "appendix", "acknowledg", "conclusion")
        if block.get("is_references_marker") or block.get("is_appendix_marker") \
                or any(k in text for k in anchor_kws):
            h = max(h, 0.75)
        elif r >= 0.35:  h *= 0.90
        else:            h *= 0.80

    return max(0.0, min(1.0, h))


def _should_keep(block: dict, zone: str, adj_score: float) -> bool:
    body_s    = _f(block.get("body_score"))
    noise_s   = _f(block.get("noise_score"))
    caption_s = _f(block.get("caption_score"))
    wc        = _i(block.get("word_count"))
    text      = normalize(block.get("text")).lower()

    if not text:
        return False

    # If roles.py explicitly assigned 'heading', include — but apply a
    # minimum threshold for narrow, low-percentile blocks.  These are often
    # map labels, legend entries, or sidebar items, not section headings.
    # Narrow layout + body-range font + weak heading score → exclude.
    if block.get("role") == "heading":
        narrow   = bool(block.get("narrow_width_like"))
        font_pct = _f(block.get("font_percentile"))
        if narrow and font_pct < 0.60 and adj_score < 0.40:
            return False
        return noise_s < 0.6 and caption_s < 0.5

    if zone == Zone.FRONT_MATTER:
        return adj_score >= 0.55

    if zone == Zone.BODY:
        return (adj_score >= max(0.42, body_s * 0.95)
                and caption_s < 0.5 and noise_s < 0.6)

    if zone == Zone.BACK_MATTER:
        anchor_kws = ("reference", "bibliograph", "appendix", "acknowledg", "conclusion")
        if any(k in text for k in anchor_kws):
            return True
        return adj_score >= 0.48 and wc <= 10

    return adj_score >= 0.45


# ── Normalisation / filtering ─────────────────────────────────────────────────

def _merge_title_lines(headings: list[dict]) -> list[dict]:
    result: list[dict] = []
    i = 0
    while i < len(headings):
        cur = dict(headings[i])
        if i + 1 < len(headings):
            nxt = headings[i + 1]
            if (cur.get("font_size") == nxt.get("font_size")
                    and cur.get("page_index") == nxt.get("page_index")
                    and _i(nxt.get("block_index")) == _i(cur.get("block_index")) + 1
                    and (_f(cur.get("font_size")) or 0) >= 14
                    and (_f(nxt.get("font_size")) or 0) >= 14):
                cur["text"] = f'{normalize(cur.get("text"))} {normalize(nxt.get("text"))}'.strip()
                cur["end_block_index"] = nxt.get("block_index")
                result.append(cur)
                i += 2
                continue
        result.append(cur)
        i += 1
    return result


def _filter_headings(headings: list[dict]) -> list[dict]:
    out = []
    for row in headings:
        text = normalize(row.get("text"))
        if not text:
            continue
        fs   = _f(row.get("font_size"))
        ital = bool(row.get("italic"))
        was_letter_spaced = bool(row.get("was_letter_spaced"))
        if is_formula_label(text):    continue
        if is_meta_line(text):        continue
        if is_contact_line(text):     continue
        if is_caption_like(text):     continue
        if is_reference_entry(text, font_size=fs, italic=ital): continue
        if is_author_line(text):      continue
        if is_author_bio(text):       continue
        # URL strings are not section headings
        if "http" in text.lower() or text.lower().endswith(".org.uk") or ".org" in text.lower():
            continue
        # Bare document codes / reference numbers (e.g. "HEAG157", "ISBN 978-...")
        import re as _re
        if _re.match(r'^[A-Z]{2,6}\d{2,}$', text.strip()):
            continue
        # Page-number + word artefacts like "27 Ownership"
        if _re.match(r'^\d{1,3}\s+[A-Z][a-z]+$', text.strip()):
            continue
        # Letter-spaced headings collapse to a single token — skip fragment check
        if not was_letter_spaced:
            if is_fragment_heading(text, font_size=fs, italic=ital): continue
        if is_sentence_heading(text): continue
        # Numbered italic captions at small font
        if (ital and fs <= 10.0 and text[0].isdigit()
                and len(text.split()) >= 4):
            continue
        out.append(row)
    return out


def _normalize_headings(headings: list[dict]) -> list[dict]:
    headings = sorted(headings, key=lambda r: _i(r.get("block_index")))
    headings = _merge_title_lines(headings)
    headings = _filter_headings(headings)
    return headings


# ── Public API ────────────────────────────────────────────────────────────────

def compute_headings(conn: sqlite3.Connection, document_id: str) -> None:
    """Collect, adjust, filter, and persist heading candidates.

    Writes du_heading_candidates. Idempotent — DELETE + INSERT.
    """
    blocks = _fetch_blocks(conn, document_id)
    if not blocks:
        return

    body_font_sizes = sorted(
        _f(b.get("font_size")) for b in blocks if b.get("font_size")
    )
    body_font = body_font_sizes[len(body_font_sizes) // 2] if body_font_sizes else 10.0

    candidates: list[dict] = []

    for block in blocks:
        raw_zone  = block.get("zone") or Zone.BODY
        zone      = _OLD_TO_NEW.get(raw_zone, Zone.BODY)
        adj_score = _adjust_heading_score(block, zone)

        if not _should_keep(block, zone, adj_score):
            continue

        candidates.append({
            "block_id":           block["block_id"],
            "block_index":        block["block_index"],
            "page_index":         block["page_index"],
            "text":               normalize(normalize_letter_spaced(block.get("text") or "")),
            "font_size":          block.get("font_size"),
            "italic":             block.get("italic"),
            "heading_score":      adj_score,
            "body_score":         _f(block.get("body_score")),
            "source":             f"headings.v1:{zone}",
            "was_letter_spaced":  bool(block.get("is_letter_spaced")),
        })

    candidates = _normalize_headings(candidates)

    conn.execute(
        "DELETE FROM du_heading_candidates WHERE block_id IN "
        "(SELECT block_id FROM du_blocks WHERE document_id = ?)",
        (document_id,),
    )
    conn.execute(
        "DELETE FROM du_heading_candidates WHERE block_id NOT IN "
        "(SELECT block_id FROM du_blocks)"
    )

    if candidates:
        conn.executemany(
            """
            INSERT INTO du_heading_candidates (
                block_id, block_index, page_index, text,
                font_size, italic, heading_score, body_score, source
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            [(c["block_id"], c["block_index"], c["page_index"], c["text"],
              c["font_size"], c["italic"], c["heading_score"],
              c["body_score"], c["source"])
             for c in candidates],
        )

    conn.commit()
