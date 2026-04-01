# src/atlas/understanding/interpret/toc.py
"""Table-of-Contents parser for Document Understanding.

Architecture
------------
The TOC is treated as *hard evidence* for section titles and hierarchy.
Rather than replacing the typography-based section tree, TOC entries are
used to verify and extend it:

  1. Match existing typography nodes by title similarity or page number
  2. Update matched nodes with TOC titles/levels (hard evidence)
  3. Insert missing TOC entries as new section nodes
  4. Keep unmatched typography nodes (L2+ subchapters not in TOC)

This combines the TOC's structural authority with the typography pass's
coverage of subchapters that TOC entries often omit.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from atlas.understanding.core.vocab import Zone
from atlas.core.similarity import title_similarity


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class TocEntry:
    number:  str | None   # "1", "1.2", "IV", None for unnumbered
    title:   str          # clean title text
    page:    int          # TOC page number (1-based, printed)
    level:   int = 1      # derived from number depth


# ── TOC entry regex ──────────────────────────────────────────────────────────

_TOC_ENTRY_RE = re.compile(
    r'^'
    r'(?:(\d+(?:\.\d+)*|[IVX]{1,5}(?:\.\d+)?|[A-Z](?:\.\d+)?)\s+)?'
    r'(.+?)'
    r'(?:\s*\.{2,}\s*|\s{4,})'
    r'(\d{1,4})\s*$',
    re.UNICODE,
)

_MIN_TOC_ENTRIES = 3
_MAX_TOC_PAGES   = 3
_MAX_TOC_BLOCKS  = 80


# ── Public API ───────────────────────────────────────────────────────────────

def extract_toc_entries(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[TocEntry]:
    """Parse TOC blocks and return structured entries."""
    toc_blocks = _fetch_toc_blocks(conn, document_id)
    if not toc_blocks:
        return []
    entries: list[TocEntry] = []
    for block in toc_blocks:
        entries.extend(_parse_block(block["text"]))
    if len(entries) < _MIN_TOC_ENTRIES:
        return []
    _assign_levels(entries)
    return entries


def merge_toc_into_section_tree(
    conn: sqlite3.Connection,
    document_id: str,
    toc_entries: list[TocEntry],
) -> None:
    """Use TOC entries to verify and extend the existing section tree.

    For each TOC entry:
    - If a matching node exists → update title/level with TOC values
    - If no match → insert as new section node
    Typography nodes without a TOC match are kept unchanged.
    """
    if not toc_entries:
        return

    page_offset = _compute_page_offset(conn, document_id)
    page_blocks  = _build_page_block_map(conn, document_id)

    # Load existing tree nodes
    existing = {
        row["section_node_id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM du_section_tree WHERE document_id = ?",
            (document_id,),
        ).fetchall()
    }

    # Title index: normalised → node_id
    title_idx: dict[str, int] = {
        _norm_title(n["title"]): nid
        for nid, n in existing.items() if n.get("title")
    }

    # Page index: page_start → list of node_ids
    page_idx_map: dict[int, list[int]] = {}
    for nid, node in existing.items():
        ps = node.get("page_start")
        if ps is not None:
            page_idx_map.setdefault(int(ps), []).append(nid)

    matched: set[int] = set()

    for entry in toc_entries:
        pg = max(0, entry.page - 1 + page_offset)
        norm = _norm_title(entry.title)

        # 1. Exact normalised title match
        node_id = title_idx.get(norm)

        # 1b. Fuzzy title match across all nodes (catches formatting differences)
        if node_id is None:
            best_sim = 0.0
            best_nid = None
            for nid, node in existing.items():
                if nid in matched:
                    continue
                sim = title_similarity(entry.title, node.get("title", ""))
                if sim > best_sim and sim >= 0.70:
                    best_sim = sim
                    best_nid = nid
            if best_nid is not None:
                node_id = best_nid

        # 2. Page + similarity match
        if node_id is None:
            for candidate in page_idx_map.get(pg, []):
                if candidate not in matched:
                    ct = existing[candidate].get("title", "")
                    if title_similarity(entry.title, ct) >= 0.70:
                        node_id = candidate
                        break

        if node_id is not None:
            matched.add(node_id)
            conn.execute(
                """
                UPDATE du_section_tree
                SET title = ?, title_normalized = ?, level = ?,
                    source = source || '+toc.v1'
                WHERE section_node_id = ?
                """,
                (entry.title, entry.title.lower(), entry.level, node_id),
            )
        else:
            # Insert missing entry
            hbid = _find_heading_block(page_blocks, pg, entry.title)
            sbi  = None
            if hbid:
                r = conn.execute(
                    "SELECT block_index FROM du_blocks WHERE block_id = ?",
                    (hbid,),
                ).fetchone()
                if r:
                    sbi = r["block_index"]
            conn.execute(
                """
                INSERT INTO du_section_tree
                    (document_id, heading_block_id, start_block_index,
                     page_start, level, title, title_normalized, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, hbid, sbi, pg,
                 entry.level, entry.title, entry.title.lower(), "toc.v1"),
            )

    conn.commit()


# ── Internal helpers ─────────────────────────────────────────────────────────

def _fetch_toc_blocks(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    from atlas.understanding.core.text_patterns import is_toc_heading

    zone_rows = conn.execute(
        """
        SELECT b.block_id, b.block_index, b.page_index, b.text
        FROM du_block_zones z JOIN du_blocks b ON b.block_id = z.block_id
        WHERE b.document_id = ? AND z.zone = ?
        ORDER BY b.block_index
        """,
        (document_id, Zone.TOC),
    ).fetchall()
    if zone_rows:
        return [dict(r) for r in zone_rows]

    all_blocks = [dict(r) for r in conn.execute(
        "SELECT block_id, block_index, page_index, text FROM du_blocks "
        "WHERE document_id = ? ORDER BY block_index",
        (document_id,),
    ).fetchall()]

    toc_idx = toc_page = None
    for i, b in enumerate(all_blocks):
        if is_toc_heading(b["text"]):
            toc_idx, toc_page = i, b["page_index"]
            break
    if toc_idx is None:
        return []

    result = []
    for b in all_blocks[toc_idx + 1:]:
        if b["page_index"] > toc_page + _MAX_TOC_PAGES:
            break
        if len(result) >= _MAX_TOC_BLOCKS:
            break
        result.append(b)
    return result


def _parse_block(text: str | None) -> list[TocEntry]:
    """Extract TOC entries from one block using a line accumulator.

    Iterates lines, accumulating them until the text matches the TOC
    pattern (title + dot leaders + page number). Handles:
    - Multi-line titles: "1\\nIntroducing Traditional\\nFarmsteads..........4"
    - Same-block multi-entries: "1.1\\nTitle A..4\\n1.2\\nTitle B..5"
    - Apostrophes and special chars: "Historic England's advice.........1"
    """
    if not text:
        return []

    entries: list[TocEntry] = []
    pending: list[str] = []

    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue

        # Try accumulated lines + current line as one entry
        candidate = " ".join(pending + [line])
        m = _TOC_ENTRY_RE.match(candidate)
        if m:
            title = m.group(2).strip(" .")
            page  = int(m.group(3))
            if title and 3 <= len(title) <= 120:
                entries.append(TocEntry(number=m.group(1), title=title, page=page))
            pending = []
            continue

        # Try current line alone
        m_alone = _TOC_ENTRY_RE.match(line)
        if m_alone:
            pending = []
            title = m_alone.group(2).strip(" .")
            page  = int(m_alone.group(3))
            if title and 3 <= len(title) <= 120:
                entries.append(TocEntry(number=m_alone.group(1), title=title, page=page))
            continue

        # Accumulate as continuation
        pending.append(line)
        if len(pending) > 4:
            pending = [line]  # prevent runaway accumulation

    return entries


def _assign_levels(entries: list[TocEntry]) -> None:
    last = 1
    for e in entries:
        if e.number:
            e.level = len(e.number.split("."))
            last = e.level
        else:
            e.level = last


def _compute_page_offset(conn: sqlite3.Connection, document_id: str) -> int:
    r = conn.execute(
        """
        SELECT b.page_index FROM du_block_zones z
        JOIN du_blocks b ON b.block_id = z.block_id
        WHERE b.document_id = ? AND z.zone = 'body'
        ORDER BY b.block_index LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    return int(r["page_index"]) if r else 0


def _build_page_block_map(conn: sqlite3.Connection, document_id: str) -> dict:
    result: dict[int, list[dict]] = {}
    for row in conn.execute(
        "SELECT block_id, block_index, page_index, text FROM du_blocks "
        "WHERE document_id = ? ORDER BY block_index",
        (document_id,),
    ).fetchall():
        result.setdefault(row["page_index"], []).append(dict(row))
    return result


def _find_heading_block(
    page_blocks: dict[int, list[dict]],
    page_idx: int,
    title: str,
) -> str | None:
    norm = _norm_title(title)
    for delta in (0, 1, -1, 2):
        for b in page_blocks.get(page_idx + delta, []):
            bt = _norm_title(b["text"])
            if bt == norm:
                return b["block_id"]
            if norm and bt and len(norm) >= 4:
                if norm in bt or bt in norm:
                    return b["block_id"]
                if title_similarity(title, b["text"]) >= 0.70:
                    return b["block_id"]
    return None


def _norm_title(text: str | None) -> str:
    from atlas.understanding.core.text_patterns import normalize_letter_spaced
    t = " ".join(normalize_letter_spaced(text or "").split()).lower()
    t = re.sub(r'^(?:\d+(?:\.\d+)*|[ivx]+(?:\.\d+)?)\s+', '', t)
    return t.replace(" ", "").strip()
