# src/atlas/understanding/measure/spacing.py
"""Layer 1 — spacing and rhythm features per block.

Reads du_blocks joined with du_block_geometry (whitespace, indent).
Writes du_block_spacing.

column_hint is absent from the schema (OE-1) — column continuity
falls back to x0-distance comparison (tolerance 40 pt).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict


def _fetch_blocks(conn: sqlite3.Connection,
                  document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT b.block_id, b.page_index, b.block_index, b.x0,
               g.indent_left, g.indent_right,
               g.centeredness,
               g.whitespace_before, g.whitespace_after
        FROM du_blocks b
        LEFT JOIN du_block_geometry g ON g.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.page_index, b.block_index
        """,
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _median(values: list) -> float | None:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    return clean[len(clean) // 2]


def _flow_median(whitespace_values: list) -> float | None:
    """Median of POSITIVE whitespace values only.

    Negative whitespace_before occurs when blocks overlap vertically —
    common in multi-column layouts, map labels, and other non-flow content.
    By restricting to positive values we get a robust estimate of the
    normal inter-block gap in the main text flow, even when the document
    contains many scattered non-flow elements (legends, map labels, etc.).
    """
    positive = sorted(float(v) for v in whitespace_values
                      if v is not None and float(v) > 0)
    if not positive:
        return None
    return positive[len(positive) // 2]


def _same_columnish(a: dict, b: dict) -> bool:
    """Approximate column continuity via x0 proximity (no column_hint yet)."""
    ax, bx = a.get("x0"), b.get("x0")
    if ax is None or bx is None:
        return True
    return abs(float(ax) - float(bx)) <= 40.0


def compute_spacing(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute spacing and rhythm features for every block.

    Writes du_block_spacing. Idempotent via INSERT OR REPLACE.
    """
    blocks = _fetch_blocks(conn, document_id)
    if not blocks:
        return

    # Use positive-only median for paragraph_gap normalization.
    # Negative whitespace_before indicates overlapping / non-flow blocks
    # (map labels, legend entries, multi-column scattered text).
    # The positive-only median gives a robust estimate of the normal
    # inter-block gap in the main text flow.
    flow_median_before = _flow_median([b.get("whitespace_before") for b in blocks])
    flow_median_after  = _flow_median([b.get("whitespace_after")  for b in blocks])
    # Keep _median for legacy paragraph_gap fields (existing callers).
    median_before = flow_median_before  # now always positive-only
    median_after  = flow_median_after

    by_page: dict[int, list[dict]] = defaultdict(list)
    for b in blocks:
        by_page[int(b["page_index"])].append(b)

    rows: list[tuple] = []

    for _, page_blocks in sorted(by_page.items()):
        for i, block in enumerate(page_blocks):
            prev = page_blocks[i - 1] if i > 0               else None
            nxt  = page_blocks[i + 1] if i + 1 < len(page_blocks) else None

            gap_before = block.get("whitespace_before")
            gap_after  = block.get("whitespace_after")

            para_gap_before = (
                float(gap_before) / max(1.0, float(median_before))
                if gap_before is not None and median_before
                else None
            )
            para_gap_after = (
                float(gap_after) / max(1.0, float(median_after))
                if gap_after is not None and median_after
                else None
            )

            indent_left  = block.get("indent_left")
            indent_right = block.get("indent_right")
            centeredness = block.get("centeredness")

            alignment_left   = 1.0 if indent_left  is not None and abs(float(indent_left))  < 10.0 else 0.0
            alignment_right  = 1.0 if indent_right is not None and abs(float(indent_right)) < 10.0 else 0.0
            alignment_center = (1.0 - min(1.0, float(centeredness))) if centeredness is not None else None

            continuation_like = 0.0
            break_like        = 0.0

            # in_flow_score: 1.0 = block is part of the normal vertical text flow.
            # 0.0 = block is spatially scattered (map label, legend, sidebar item).
            # A block is "in flow" when its whitespace_before is positive AND
            # within a reasonable multiple of the flow median (not a wild outlier).
            # Negative gap = block overlaps or is placed above the previous block
            # in reading order → definitively not in normal flow.
            if gap_before is None or flow_median_before is None or flow_median_before <= 0:
                in_flow_score = 0.5  # unknown — no data
            elif float(gap_before) < 0:
                # Negative gap in a single-column document = non-flow (map label etc.)
                # BUT in multi-column layouts the second column always has negative
                # gap relative to the previous block in the first column.
                # Without column detection (OE-1) we cannot distinguish these cases.
                # Use 0.3 (weak signal: probably not normal flow, but not certain).
                in_flow_score = 0.3
            else:
                ratio = float(gap_before) / float(flow_median_before)
                # Normal flow: 0.1× to 5× the median gap.
                # Beyond 5× = large section break (still flow, but major break).
                # The score decays linearly from 1.0 at ratio=1.0 toward 0.0.
                if ratio <= 5.0:
                    in_flow_score = max(0.2, 1.0 - abs(ratio - 1.0) / 5.0)
                else:
                    in_flow_score = 0.2  # very large gap, probably a page break

            if prev is not None and _same_columnish(prev, block):
                if gap_before is not None and median_before and float(gap_before) <= float(median_before) * 1.25:
                    continuation_like += 0.5
                if indent_left is not None and abs(float(indent_left)) < 12.0:
                    continuation_like += 0.25
            else:
                break_like += 0.5

            if para_gap_before is not None and para_gap_before >= 1.6:
                break_like += 0.5
            if nxt is not None and not _same_columnish(block, nxt):
                break_like += 0.2

            rows.append((
                block["block_id"],
                gap_before, gap_after,
                para_gap_before, para_gap_after,
                indent_left, indent_right,
                alignment_left, alignment_center, alignment_right,
                min(1.0, continuation_like),
                min(1.0, break_like),
                in_flow_score,
            ))

    conn.executemany(
        """
        INSERT INTO du_block_spacing (
            block_id,
            line_gap_before, line_gap_after,
            paragraph_gap_before, paragraph_gap_after,
            indent_left, indent_right,
            alignment_left, alignment_center, alignment_right,
            continuation_like, break_like,
            in_flow_score
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            line_gap_before      = excluded.line_gap_before,
            line_gap_after       = excluded.line_gap_after,
            paragraph_gap_before = excluded.paragraph_gap_before,
            paragraph_gap_after  = excluded.paragraph_gap_after,
            indent_left          = excluded.indent_left,
            indent_right         = excluded.indent_right,
            alignment_left       = excluded.alignment_left,
            alignment_center     = excluded.alignment_center,
            alignment_right      = excluded.alignment_right,
            continuation_like    = excluded.continuation_like,
            break_like           = excluded.break_like,
            in_flow_score        = excluded.in_flow_score
        """,
        rows,
    )
    conn.commit()
