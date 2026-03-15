from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import psycopg


class DURepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # ---------------------------------------------------------
    # Document Context
    # ---------------------------------------------------------

    def insert_document_context(self, ctx) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into du_document_context (
                    document_id,
                    source_kind,
                    text_source,
                    geometry_source,
                    reading_order_source,
                    has_native_text,
                    has_reliable_geometry,
                    has_reliable_reading_order,
                    text_confidence,
                    geometry_confidence,
                    reading_order_confidence,
                    notes
                )
                values (
                    %(document_id)s,
                    %(source_kind)s,
                    %(text_source)s,
                    %(geometry_source)s,
                    %(reading_order_source)s,
                    %(has_native_text)s,
                    %(has_reliable_geometry)s,
                    %(has_reliable_reading_order)s,
                    %(text_confidence)s,
                    %(geometry_confidence)s,
                    %(reading_order_confidence)s,
                    %(notes)s
                )
                on conflict (document_id) do nothing
                """,
                asdict(ctx),
            )

    # ---------------------------------------------------------
    # Pages
    # ---------------------------------------------------------

    def insert_pages(self, pages: Iterable) -> None:
        pages = list(pages)
        if not pages:
            return

        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into du_pages (
                    document_id,
                    page_index,
                    width,
                    height,
                    image_based,
                    native_text_present,
                    page_confidence
                )
                values (
                    %(document_id)s,
                    %(page_index)s,
                    %(width)s,
                    %(height)s,
                    %(image_based)s,
                    %(native_text_present)s,
                    %(page_confidence)s
                )
                on conflict (document_id, page_index) do nothing
                """,
                [asdict(p) for p in pages],
            )

    # ---------------------------------------------------------
    # Blocks
    # ---------------------------------------------------------

    def insert_blocks(self, blocks: Iterable) -> None:
        blocks = list(blocks)
        if not blocks:
            return

        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into du_blocks (
                    document_id,
                    page_index,
                    block_index,
                    start_char,
                    end_char,
                    text,
                    x0,
                    y0,
                    x1,
                    y1,
                    page_y0,
                    page_y1,
                    doc_y0,
                    doc_y1,
                    text_source,
                    geometry_source,
                    text_confidence,
                    geometry_confidence,
                    reading_order_confidence
                )
                values (
                    %(document_id)s,
                    %(page_index)s,
                    %(block_index)s,
                    %(start_char)s,
                    %(end_char)s,
                    %(text)s,
                    %(x0)s,
                    %(y0)s,
                    %(x1)s,
                    %(y1)s,
                    %(page_y0)s,
                    %(page_y1)s,
                    %(doc_y0)s,
                    %(doc_y1)s,
                    %(text_source)s,
                    %(geometry_source)s,
                    %(text_confidence)s,
                    %(geometry_confidence)s,
                    %(reading_order_confidence)s
                )
                on conflict (document_id, block_index) do nothing
                """,
                [asdict(b) for b in blocks],
            )

    # ---------------------------------------------------------
    # Reads
    # ---------------------------------------------------------

    def _resolve_document_path_column(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'documents'
                order by ordinal_position
                """
            )
            cols = {row[0] for row in cur.fetchall()}

        for candidate in ("path", "relative_path", "file_path", "source_path"):
            if candidate in cols:
                return candidate

        return "document_id"

    def fetch_documents(self):
        path_col = self._resolve_document_path_column()

        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                select document_id, {path_col}
                from documents
                order by {path_col}
                """
            )
            return cur.fetchall()

    def fetch_text_segments(self, document_id):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select
                    page_index,
                    segment_index,
                    text
                from text_segments
                where document_id = %s
                order by page_index, segment_index
                """,
                (document_id,),
            )
            return cur.fetchall()

    def fetch_blocks(self, document_id):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select
                    block_id,
                    block_index,
                    page_index,
                    text
                from du_blocks
                where document_id = %s
                order by block_index
                """,
                (document_id,),
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
            
def compute_columns(self, document_id: str):

    from atlas.document_understanding.layout.column_detection import (
        compute_and_store_columns,
    )

    compute_and_store_columns(self, document_id)
    
def compute_section_tree(self, document_id: str):

    from atlas.document_understanding.structure.section_tree import (
        compute_section_tree,
    )

    compute_section_tree(self, document_id)
