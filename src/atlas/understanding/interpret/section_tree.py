# src/atlas/understanding/interpret/section_tree.py
"""Layer 3 — build the hierarchical section tree.

Reads heading candidates and zone assignments, applies style-model
clustering, and writes du_section_tree.

Level assignment strategy (in priority order):
  1. Chapter number prefix → direct level from depth of numbering
     '1 TIMBER CONSTRUCTION' → L1
     '1.2 Materials'         → L2
     '1.2.1 Lumber'          → L3
  2. Back-matter zone or anchor keyword → L1
  3. Style model (font_size, bold, italic, all_caps, ...) → Ln
  4. Italic + short → min L2

Zone names come from vocab.Zone. The old "front"/"body"/"back"
strings are replaced throughout.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from atlas.core.logging import get_logger
_log = get_logger("atlas.du.section_tree")

from atlas.understanding.core.vocab import Zone
from atlas.understanding.core.text_patterns import (
    is_reference_heading, is_appendix_heading, normalize,
)
from atlas.understanding.core.section_labels import ALL_BACK_MATTER_HEADINGS
from atlas.understanding.core.style_model import (
    build_style_model, style_key, chapter_number_level,
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

def _norm(text: str | None) -> str:
    return normalize(text)


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_headings(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Fetch heading candidates with full typographic attributes for style_key."""
    return [dict(r) for r in conn.execute(
        """
        SELECT h.block_id, h.block_index, h.page_index, h.text,
               h.font_size, h.italic, h.heading_score, h.body_score,
               COALESCE(t.bold,       0) AS bold,
               COALESCE(t.all_caps,   0) AS all_caps,
               COALESCE(t.small_caps, 0) AS small_caps,
               COALESCE(t.color_rank, 0) AS color_rank,
               COALESCE(t.is_serif,   0) AS is_serif
        FROM du_heading_candidates h
        JOIN du_blocks b ON b.block_id = h.block_id
        LEFT JOIN du_block_typography t ON t.block_id = h.block_id
        WHERE b.document_id = ?
        ORDER BY h.block_index
        """,
        (document_id,),
    ).fetchall()]


def _fetch_zone_map(conn: sqlite3.Connection, document_id: str) -> dict[int, str]:
    rows = conn.execute(
        """
        SELECT b.block_index, z.zone
        FROM du_block_zones z
        JOIN du_blocks b ON b.block_id = z.block_id
        WHERE b.document_id = ?
        """,
        (document_id,),
    ).fetchall()
    return {_i(r["block_index"]): (r["zone"] or Zone.BODY) for r in rows}


# ── Tree-building helpers ─────────────────────────────────────────────────────

_BACK_ZONES = {Zone.BACK_MATTER, Zone.REFERENCES, Zone.APPENDIX}


def _is_top_level_text(text: str) -> bool:
    low = _norm(text).lower()
    return (
        "conclusion" in low
        or "acknowledg" in low
        or is_reference_heading(low)
        or is_appendix_heading(low)
        or low in ALL_BACK_MATTER_HEADINGS
    )


def _looks_terminal_major(h: dict) -> bool:
    return (
        _i(h.get("block_index")) >= 120
        and not bool(h.get("italic"))
        and _f(h.get("font_size")) >= 10.0
        and _f(h.get("heading_score")) >= 0.5
        and 1 <= len((_norm(h.get("text")) or "").split()) <= 4
    )


def _is_front_meta_like(h: dict) -> bool:
    text = _norm(h.get("text"))
    if not text:
        return True
    wc    = len(text.split())
    fs    = _f(h.get("font_size"))
    ital  = bool(h.get("italic"))
    hs    = _f(h.get("heading_score"))
    if 1 <= wc <= 4 and not ital and hs >= 0.5:
        return False
    if ital and wc <= 3 and fs <= 10.0:
        return False
    if fs >= 14.0:
        return True
    return hs < 0.55


def _dedupe(headings: list[dict]) -> list[dict]:
    seen, out = set(), []
    for h in headings:
        key = (_i(h.get("block_index")), _norm(h.get("text")).lower())
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def _fetch_title_block_ids(conn: sqlite3.Connection, document_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT r.block_id FROM du_block_roles r
        JOIN du_blocks b ON b.block_id = r.block_id
        WHERE b.document_id = ? AND r.role = 'title'
        """,
        (document_id,),
    ).fetchall()
    return {str(r[0]) for r in rows}


def _detect_title(headings: list[dict],
                  title_block_ids: set[str] | None = None) -> dict | None:
    if not headings:
        return None
    if title_block_ids:
        titled = [h for h in headings if str(h.get("block_id")) in title_block_ids]
        if titled:
            return sorted(titled, key=lambda h: _i(h.get("block_index")))[0]
    max_fs = max(_f(h.get("font_size")) for h in headings)
    cands  = sorted(
        [h for h in headings if _f(h.get("font_size")) == max_fs],
        key=lambda h: _i(h.get("block_index")),
    )
    return cands[0] if cands else None


def _final_level(h: dict, zone: str, style_levels: dict) -> int:
    """Determine heading level.

    Priority:
    1. Chapter number prefix (e.g. '1.2.3 Title' → L3) — most reliable.
    2. Back-matter zone or anchor keyword → L1.
    3. Style model level from typographic clustering.
    4. Italic + short → push to min L2.

    The old rule `if not ital and wc <= 5: level = min(level, 1)` is
    removed — it incorrectly forced numbered subsections like
    '1.2.1 Lumber' to L1 when the style model said L2 or L3.
    """
    text = _norm(h.get("text"))

    # 1. Chapter number prefix overrides everything
    num_level = chapter_number_level(text)
    if num_level is not None:
        return num_level

    # 2. Back-matter / anchor keywords → always L1
    if zone in _BACK_ZONES:
        return 1
    if _is_top_level_text(text) or _looks_terminal_major(h):
        return 1

    # 3. Style model
    level = style_levels.get(style_key(h), 1)

    # 4. Italic short headings are sub-headings
    ital = bool(h.get("italic"))
    wc   = len(text.split()) if text else 0
    if ital and 1 <= wc <= 6:
        level = max(level, 2)

    return level


# ── Public API ────────────────────────────────────────────────────────────────

def compute_section_tree(conn: sqlite3.Connection, document_id: str, ocr_mode: bool = False) -> None:
    """Build the section hierarchy from heading candidates and zones.

    Strategy:
    1. Build the typography-based section tree (always).
    2. If the document has a parseable TOC, merge TOC entries into the
       tree: TOC titles/levels override typography values where they match,
       and missing TOC entries are inserted as new nodes.

    The TOC is treated as hard evidence — its titles and hierarchy are
    authoritative.  The typography pass covers L2+ subchapters that TOC
    entries often omit.

    Writes du_section_tree. Idempotent — DELETE + INSERT.
    """
    from atlas.understanding.interpret.toc import extract_toc_entries, merge_toc_into_section_tree

    conn.execute("DELETE FROM du_section_tree WHERE document_id = ?", (document_id,))
    conn.commit()

    raw_headings = _fetch_headings(conn, document_id)

    # OCR mode: keep only high-confidence candidates to prevent the
    # section-tree explosion caused by OCR word-boxes scoring as headings.
    if ocr_mode:
        import re as _re
        def _ocr_heading_ok(h: dict) -> bool:
            if (h.get("heading_score") or 0.0) < 0.60:
                return False
            text = (h.get("text") or "").strip()
            words = text.split()
            # Single short token that is not a real word (e.g. "ASOAL")
            if len(words) == 1 and len(text) <= 6:
                return False
            # Titelseiten-Stempel: ≤ 2 Wörter auf den ersten 3 Seiten
            page = h.get("page_index") or 0
            if len(words) <= 2 and page < 3:
                return False
            return True
        raw_headings = [h for h in raw_headings if _ocr_heading_ok(h)]

    zone_map     = _fetch_zone_map(conn, document_id)
    title_ids    = _fetch_title_block_ids(conn, document_id)

    headings = _dedupe(raw_headings)
    if not headings:
        conn.commit()
        return

    title = _detect_title(headings, title_block_ids=title_ids)

    structural: list[dict] = []
    for h in headings:
        if h is title:
            continue
        idx  = _i(h.get("block_index"))
        zone = zone_map.get(idx, Zone.BODY)
        if zone == Zone.FRONT_MATTER and _is_front_meta_like(h):
            continue
        h2 = dict(h)
        h2["zone"] = zone
        structural.append(h2)

    structural.sort(key=lambda h: _i(h.get("block_index")))

    if not structural:
        conn.commit()
        return

    body_headings = [
        h for h in structural
        if h.get("zone") not in _BACK_ZONES
        and not _is_top_level_text(h.get("text"))
        and not _looks_terminal_major(h)
    ]
    style_model  = build_style_model(body_headings or structural)
    style_levels = style_model["levels"]

    conn.execute("DELETE FROM du_section_tree WHERE document_id = ?", (document_id,))

    rows: list[tuple] = []
    stack: list[dict] = []
    node_id = 1

    for h in structural:
        zone  = h.get("zone", Zone.BODY)
        idx   = _i(h.get("block_index"))
        end   = _i(h.get("end_block_index", idx))
        text  = _norm(h.get("text")) or f"Section {node_id}"
        level = _final_level(h, zone, style_levels)

        if zone in _BACK_ZONES or _is_top_level_text(text) or _looks_terminal_major(h):
            stack = []
        else:
            while stack and _i(stack[-1]["level"]) >= level:
                stack.pop()

        parent = stack[-1]["node_id"] if stack else None
        if parent is None:
            level = 1
        else:
            # Prevent level jumps larger than 1 step down:
            # L1 → L3 is corrected to L1 → L2.
            # This enforces the invariant that a child is at most one
            # level deeper than its parent.
            parent_level = _i(stack[-1]["level"]) if stack else 0
            if level > parent_level + 1:
                level = parent_level + 1

        rows.append((
            document_id, parent, h.get("block_id"),
            idx, end, h.get("page_index"), h.get("page_index"),
            level, text, text.lower(),
            f"section_tree.v1:{zone}",
        ))

        if zone not in _BACK_ZONES:
            stack.append({"node_id": node_id, "level": level})

        node_id += 1

    if rows:
        valid_block_ids = {
            r[0] for r in conn.execute(
                "SELECT block_id FROM du_blocks WHERE document_id = ?",
                (document_id,),
            ).fetchall()
        }
        sanitized = []
        for row in rows:
            hbid = row[2] if row[2] in valid_block_ids else None
            sanitized.append((row[0], row[1], hbid) + row[3:])

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.executemany(
                """
                INSERT INTO du_section_tree (
                    document_id, parent_section_node_id, heading_block_id,
                    start_block_index, end_block_index,
                    page_start, page_end,
                    level, title, title_normalized, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                sanitized,
            )
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    _log.debug("section_tree doc=%s: %d sections written",
               document_id[:12], len(rows))
    if len(rows) == 0:
        _log.warning("section_tree doc=%s: 0 sections",
                     document_id[:12])
    conn.commit()

    # ── TOC merge ─────────────────────────────────────────────────────────────
    # Apply TOC as hard evidence on top of the typography-based tree.
    # This corrects titles/levels and fills in missing L1 entries.
    toc_entries = extract_toc_entries(conn, document_id)
    if toc_entries:
        merge_toc_into_section_tree(conn, document_id, toc_entries)
