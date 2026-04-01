# src/atlas/understanding/segmentation/blocks.py
"""Build du_documents, du_pages, and du_blocks from du_layout_lines.

Reads pre-extracted layout lines from the database, groups them into
pages, induces blocks via block_segmentation.induce_blocks_from_lines,
and writes the results back. This is the entry point for the entire
DU pipeline — nothing downstream runs without these three tables filled.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from atlas.understanding.segmentation.block_segmentation import (
    InducedBlock,
    LayoutLine,
    induce_blocks_from_lines,
)


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_layout_lines(conn: sqlite3.Connection,
                         document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            page_index, reading_order, text,
            x0, y0, x1, y1,
            page_width, page_height,
            font_name, font_size, font_flags,
            is_bold, is_italic
        FROM du_layout_lines
        WHERE document_id = ?
        ORDER BY page_index, reading_order
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# ── Layout line grouping ──────────────────────────────────────────────────────

def _group_by_page(rows: list[dict]) -> dict[int, list[LayoutLine]]:
    pages: dict[int, list[LayoutLine]] = {}
    for row in rows:
        line = LayoutLine(
            page_index=int(row["page_index"]),
            reading_order=int(row["reading_order"]),
            text=row["text"] or "",
            x0=row["x0"],
            y0=row["y0"],
            x1=row["x1"],
            y1=row["y1"],
            page_width=row["page_width"],
            page_height=row["page_height"],
            font_name=row.get("font_name"),
            font_size=row.get("font_size"),
            font_flags=row.get("font_flags"),
            is_bold=bool(row.get("is_bold") or False),
            is_italic=bool(row.get("is_italic") or False),
        )
        pages.setdefault(line.page_index, []).append(line)
    return dict(sorted(pages.items()))


# ── Database writes ───────────────────────────────────────────────────────────

def _write_du_document(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute(
        """
        INSERT INTO du_documents (
            document_id, source_kind, text_source, geometry_source,
            has_native_text, has_reliable_geometry
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (document_id) DO NOTHING
        """,
        (document_id, "born_digital_pdf", "pdf_native", "pdf", 1, 1),
    )


def _write_pages(conn: sqlite3.Connection,
                  document_id: str,
                  page_map: dict[int, list[LayoutLine]]) -> None:
    rows = []
    for page_index, lines in page_map.items():
        page_width  = next((l.page_width  for l in lines if l.page_width  is not None), None)
        page_height = next((l.page_height for l in lines if l.page_height is not None), None)
        rows.append((document_id, page_index, page_width, page_height))

    conn.executemany(
        """
        INSERT INTO du_pages (document_id, page_index, width, height)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (document_id, page_index) DO NOTHING
        """,
        rows,
    )


def _write_blocks(conn: sqlite3.Connection,
                   document_id: str,
                   page_map: dict[int, list[LayoutLine]]) -> None:
    rows = []
    block_index = 0

    for page_index in sorted(page_map.keys()):
        induced: list[InducedBlock] = induce_blocks_from_lines(page_map[page_index])
        for block in induced:
            block_id = str(uuid.uuid4())
            rows.append((
                block_id, document_id, block_index, page_index,
                block.text,
                block.x0, block.y0, block.x1, block.y1,
                None, None,          # doc_y0, doc_y1 filled by geometry.py
                "pdf_native", "pdf",
            ))
            block_index += 1

    conn.executemany(
        """
        INSERT INTO du_blocks (
            block_id, document_id, block_index, page_index,
            text, x0, y0, x1, y1,
            doc_y0, doc_y1,
            text_source, geometry_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (document_id, block_index) DO NOTHING
        """,
        rows,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def build_document(conn: sqlite3.Connection, document_id: str) -> bool:
    """Segment one document into blocks and persist the results.

    Reads from du_layout_lines, writes to du_documents, du_pages,
    and du_blocks. Idempotent — ON CONFLICT DO NOTHING on all inserts.

    Returns:
        True if layout lines were found and blocks were written,
        False if the document has no layout lines yet.
    """
    raw = _fetch_layout_lines(conn, document_id)
    if not raw:
        return False

    page_map = _group_by_page(raw)

    _write_du_document(conn, document_id)
    _write_pages(conn, document_id, page_map)
    _write_blocks(conn, document_id, page_map)
    conn.commit()

    return True
