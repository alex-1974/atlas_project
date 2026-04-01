# src/atlas/understanding/measure/topology.py
"""Layer 1 — page-neighbourhood features per block.

Reads du_blocks (joined with du_block_geometry for page_y_ratio).
Writes du_block_topology.

Note: column_hint is not used here because the column is absent from
the schema until column detection is implemented (OE-1, Phase 4).
same_column_prev/next_like default to 0.5 (unknown) until then.

repeated_hint lives in du_block_furniture, NOT here (Bug 3 fix).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict


def _fetch_blocks(conn: sqlite3.Connection,
                  document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT b.block_id, b.page_index, b.block_index,
               g.page_y_ratio
        FROM du_blocks b
        LEFT JOIN du_block_geometry g ON g.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.page_index, b.block_index
        """,
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def compute_topology(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute page-neighbourhood features for every block.

    Writes du_block_topology. Idempotent via INSERT OR REPLACE.
    """
    blocks = _fetch_blocks(conn, document_id)
    if not blocks:
        return

    by_page: dict[int, list[dict]] = defaultdict(list)
    for b in blocks:
        by_page[int(b["page_index"])].append(b)

    rows: list[tuple] = []
    for page_index, page_blocks in sorted(by_page.items()):
        n = len(page_blocks)
        for i, block in enumerate(page_blocks):
            prev = page_blocks[i - 1] if i > 0     else None
            nxt  = page_blocks[i + 1] if i + 1 < n else None

            # column_hint not available yet → neutral 0.5
            same_col_prev = 0.5
            same_col_next = 0.5

            odd_even = "odd" if page_index % 2 == 1 else "even"

            early = 1.0 - (i / max(1, n - 1)) if n > 1 else 1.0
            late  = i / max(1, n - 1)          if n > 1 else 1.0

            rows.append((
                block["block_id"],
                int(prev is not None),   # same_page_prev
                int(nxt  is not None),   # same_page_next
                int(prev is None),        # page_transition_before
                int(nxt  is None),        # page_transition_after
                same_col_prev,
                same_col_next,
                odd_even,
                early,
                late,
            ))

    conn.executemany(
        """
        INSERT INTO du_block_topology (
            block_id,
            same_page_prev, same_page_next,
            page_transition_before, page_transition_after,
            same_column_prev_like, same_column_next_like,
            odd_even_page,
            early_on_page_score, late_on_page_score
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            same_page_prev         = excluded.same_page_prev,
            same_page_next         = excluded.same_page_next,
            page_transition_before = excluded.page_transition_before,
            page_transition_after  = excluded.page_transition_after,
            same_column_prev_like  = excluded.same_column_prev_like,
            same_column_next_like  = excluded.same_column_next_like,
            odd_even_page          = excluded.odd_even_page,
            early_on_page_score    = excluded.early_on_page_score,
            late_on_page_score     = excluded.late_on_page_score
        """,
        rows,
    )
    conn.commit()
