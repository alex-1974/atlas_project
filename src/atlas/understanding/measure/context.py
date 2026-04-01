# src/atlas/understanding/measure/context.py
"""Layer 1 — positional document-phase scores per block.

Purely positional: derives front_matter, body, and back_matter scores
from doc_y_ratio alone. No role knowledge — that invariant is enforced
here by design.

Reads du_blocks (doc_y0, doc_y1) and du_block_geometry (doc_y_ratio).
Writes du_block_context.
"""
from __future__ import annotations

import sqlite3


# Thresholds from ARCHITECTURE-DU-PIPELINE.md §context.py
_FRONT_MAX = 0.18
_BACK_MIN  = 0.78


def _phase_scores(doc_y_ratio: float | None) -> tuple[float, float, float]:
    """Return (front_matter_score, body_score, back_matter_score)."""
    if doc_y_ratio is None:
        return 0.0, 1.0, 0.0          # unknown position → assume body
    r = float(doc_y_ratio)
    if r <= _FRONT_MAX:
        front = 1.0 - (r / _FRONT_MAX)
        return round(front, 4), 0.0, 0.0
    if r >= _BACK_MIN:
        back = (r - _BACK_MIN) / (1.0 - _BACK_MIN)
        return 0.0, 0.0, round(back, 4)
    return 0.0, 1.0, 0.0


def compute_context(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute positional phase scores for every block.

    Writes du_block_context. Idempotent via INSERT OR REPLACE.
    """
    rows_raw = conn.execute(
        """
        SELECT b.block_id,
               g.doc_y_ratio,
               g.page_y_ratio
        FROM du_blocks b
        LEFT JOIN du_block_geometry g ON g.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()

    if not rows_raw:
        return

    rows: list[tuple] = []
    for r in rows_raw:
        doc_y_ratio  = r["doc_y_ratio"]
        page_y_ratio = r["page_y_ratio"]
        front, body, back = _phase_scores(doc_y_ratio)
        rows.append((
            r["block_id"],
            doc_y_ratio,
            page_y_ratio,
            front,
            body,
            back,
        ))

    conn.executemany(
        """
        INSERT INTO du_block_context (
            block_id,
            doc_y_ratio, page_y_ratio,
            front_matter_score, body_score, back_matter_score
        ) VALUES (?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            doc_y_ratio        = excluded.doc_y_ratio,
            page_y_ratio       = excluded.page_y_ratio,
            front_matter_score = excluded.front_matter_score,
            body_score         = excluded.body_score,
            back_matter_score  = excluded.back_matter_score
        """,
        rows,
    )
    conn.commit()
