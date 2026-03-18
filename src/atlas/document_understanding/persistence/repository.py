# src/atlas/document_understanding/persistence/repository.py
from __future__ import annotations

from statistics import median
from typing import Any

from atlas.document_understanding.core.coordinate_system import (
    DocumentCoordinateSystem,
)


class Repository:
    def __init__(self, conn) -> None:
        self.conn = conn

    # -------------------------------------------------------------------------
    # helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _rows_to_map(rows: list[dict], key: str = "block_id") -> dict[Any, dict]:
        return {row[key]: row for row in rows}

    @staticmethod
    def _median_or_none(values: list[float | int | None]) -> float | None:
        clean = [float(v) for v in values if v is not None]
        if not clean:
            return None
        return float(median(clean))

    def _fetch_dicts(self, sql: str, params: tuple[Any, ...]) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return
        with self.conn.cursor() as cur:
            cur.executemany(sql, rows)
        self.conn.commit()

    # -------------------------------------------------------------------------
    # destructive reset for reruns
    # -------------------------------------------------------------------------

    def delete_du_document(self, document_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                delete from du_block_roles
                where block_id in (
                    select block_id
                    from du_blocks
                    where document_id = %s
                )
                """,
                (document_id,),
            )
            cur.execute(
                """
                delete from du_block_signals
                where block_id in (
                    select block_id
                    from du_blocks
                    where document_id = %s
                )
                """,
                (document_id,),
            )
            cur.execute(
                """
                delete from du_block_topology
                where block_id in (
                    select block_id
                    from du_blocks
                    where document_id = %s
                )
                """,
                (document_id,),
            )
            cur.execute(
                """
                delete from du_block_geometry
                where block_id in (
                    select block_id
                    from du_blocks
                    where document_id = %s
                )
                """,
                (document_id,),
            )
            cur.execute(
                """
                delete from du_block_layout_features
                where block_id in (
                    select block_id
                    from du_blocks
                    where document_id = %s
                )
                """,
                (document_id,),
            )
            cur.execute(
                """
                delete from du_block_zone_memberships
                where block_id in (
                    select block_id
                    from du_blocks
                    where document_id = %s
                )
                """,
                (document_id,),
            )
            cur.execute(
                "delete from du_zone_hypotheses where document_id = %s",
                (document_id,),
            )
            cur.execute(
                "delete from du_semantic_zones where document_id = %s",
                (document_id,),
            )
            cur.execute(
                "delete from du_section_tree where document_id = %s",
                (document_id,),
            )
            cur.execute(
                "delete from du_blocks where document_id = %s",
                (document_id,),
            )
            cur.execute(
                "delete from du_pages where document_id = %s",
                (document_id,),
            )
            cur.execute(
                "delete from du_document_context where document_id = %s",
                (document_id,),
            )
            cur.execute(
                """
                update documents
                set
                    du_document_type = null,
                    du_document_type_secondary = null,
                    du_document_type_margin = null,
                    du_document_type_confidence = null,
                    du_document_type_ambiguous = false
                where document_id = %s
                """,
                (document_id,),
            )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # DU build / segmentation persistence
    # -------------------------------------------------------------------------

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
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (document_id) do update set
                    source_kind = excluded.source_kind,
                    text_source = excluded.text_source,
                    geometry_source = excluded.geometry_source,
                    reading_order_source = excluded.reading_order_source,
                    has_native_text = excluded.has_native_text,
                    has_reliable_geometry = excluded.has_reliable_geometry,
                    has_reliable_reading_order = excluded.has_reliable_reading_order,
                    text_confidence = excluded.text_confidence,
                    geometry_confidence = excluded.geometry_confidence,
                    reading_order_confidence = excluded.reading_order_confidence,
                    notes = excluded.notes
                """,
                (
                    ctx.document_id,
                    ctx.source_kind,
                    ctx.text_source,
                    ctx.geometry_source,
                    ctx.reading_order_source,
                    ctx.has_native_text,
                    ctx.has_reliable_geometry,
                    ctx.has_reliable_reading_order,
                    ctx.text_confidence,
                    ctx.geometry_confidence,
                    ctx.reading_order_confidence,
                    ctx.notes,
                ),
            )
        self.conn.commit()

    def insert_pages(self, pages) -> None:
        rows = [
            (
                p.document_id,
                p.page_index,
                p.width,
                p.height,
                p.image_based,
                p.native_text_present,
                p.page_confidence,
            )
            for p in pages
        ]
        if not rows:
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
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (document_id, page_index) do update set
                    width = excluded.width,
                    height = excluded.height,
                    image_based = excluded.image_based,
                    native_text_present = excluded.native_text_present,
                    page_confidence = excluded.page_confidence
                """,
                rows,
            )
        self.conn.commit()

    def insert_blocks(self, blocks) -> None:
        import uuid

        rows = [
            (
                str(uuid.uuid4()),
                b.document_id,
                b.page_index,
                b.block_index,
                b.start_char,
                b.end_char,
                b.text,
                b.x0,
                b.y0,
                b.x1,
                b.y1,
                b.page_y0,
                b.page_y1,
                b.doc_y0,
                b.doc_y1,
                b.text_source,
                b.geometry_source,
                b.text_confidence,
                b.geometry_confidence,
                b.reading_order_confidence,
            )
            for b in blocks
        ]
        if not rows:
            return

        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into du_blocks (
                    block_id,
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
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (document_id, block_index) do update set
                    page_index = excluded.page_index,
                    start_char = excluded.start_char,
                    end_char = excluded.end_char,
                    text = excluded.text,
                    x0 = excluded.x0,
                    y0 = excluded.y0,
                    x1 = excluded.x1,
                    y1 = excluded.y1,
                    page_y0 = excluded.page_y0,
                    page_y1 = excluded.page_y1,
                    doc_y0 = excluded.doc_y0,
                    doc_y1 = excluded.doc_y1,
                    text_source = excluded.text_source,
                    geometry_source = excluded.geometry_source,
                    text_confidence = excluded.text_confidence,
                    geometry_confidence = excluded.geometry_confidence,
                    reading_order_confidence = excluded.reading_order_confidence
                """,
                rows,
            )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # source text segments for DU segmentation
    # -------------------------------------------------------------------------

    def fetch_text_segments(self, document_id: str):
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

    # -------------------------------------------------------------------------
    # document / block base
    # -------------------------------------------------------------------------

    def fetch_documents(self) -> list[dict]:
        return self._fetch_dicts(
            """
            select d.document_id, d.file_path, d.relative_path, d.file_name
            from documents d
            order by d.relative_path, d.file_name
            """,
            (),
        )

    def fetch_blocks(self, doc_id: str) -> list[dict]:
        return self._fetch_dicts(
            """
            select
                b.block_id,
                b.document_id,
                b.page_index,
                b.block_index,
                b.start_char,
                b.end_char,
                b.text,
                b.x0,
                b.y0,
                b.x1,
                b.y1,
                b.page_y0,
                b.page_y1,
                b.doc_y0,
                b.doc_y1,
                b.text_source,
                b.geometry_source,
                b.text_confidence,
                b.geometry_confidence,
                b.reading_order_confidence,
                p.width as page_width,
                p.height as page_height
            from du_blocks b
            left join du_pages p
              on p.document_id = b.document_id
             and p.page_index = b.page_index
            where b.document_id = %s
            order by b.block_index
            """,
            (doc_id,),
        )

    # -------------------------------------------------------------------------
    # coordinate system
    # -------------------------------------------------------------------------

    def fetch_coordinate_system(self, doc_id: str) -> DocumentCoordinateSystem:
        blocks = self.fetch_blocks(doc_id)
        if not blocks:
            return DocumentCoordinateSystem(
                page_width=None,
                page_height=None,
                document_height=None,
                body_font_size=None,
                median_line_gap=None,
                median_paragraph_gap=None,
                default_column_left=None,
                default_column_right=None,
                column_count=None,
            )

        page_width = self._median_or_none([b.get("page_width") for b in blocks])
        page_height = self._median_or_none([b.get("page_height") for b in blocks])

        doc_y1_values = [b.get("doc_y1") for b in blocks if b.get("doc_y1") is not None]
        document_height = max(doc_y1_values) if doc_y1_values else None

        typography = self.fetch_typography_features(doc_id)
        font_sizes = [
            row.get("font_size")
            for row in typography.values()
            if row.get("font_size") is not None
        ]
        body_font_size = self._median_or_none(font_sizes)

        geometry = self.fetch_geometry_features(doc_id)
        whitespace_before = [
            row.get("whitespace_before")
            for row in geometry.values()
            if row.get("whitespace_before") is not None
            and float(row.get("whitespace_before")) > 0.0
        ]
        median_line_gap = self._median_or_none(whitespace_before)

        paragraph_like = [
            float(g)
            for g in whitespace_before
            if median_line_gap is not None and float(g) > median_line_gap * 1.35
        ]
        median_paragraph_gap = self._median_or_none(paragraph_like) or median_line_gap

        x0_values = [b.get("x0") for b in blocks if b.get("x0") is not None]
        x1_values = [b.get("x1") for b in blocks if b.get("x1") is not None]

        default_column_left = self._median_or_none(x0_values)
        default_column_right = self._median_or_none(x1_values)

        return DocumentCoordinateSystem(
            page_width=page_width,
            page_height=page_height,
            document_height=document_height,
            body_font_size=body_font_size,
            median_line_gap=median_line_gap,
            median_paragraph_gap=median_paragraph_gap,
            default_column_left=default_column_left,
            default_column_right=default_column_right,
            column_count=1,
        )

    # -------------------------------------------------------------------------
    # geometry
    # -------------------------------------------------------------------------

    def fetch_geometry_features(self, doc_id: str) -> dict[Any, dict]:
        rows = self._fetch_dicts(
            """
            select
                g.block_id,
                g.width,
                g.height,
                g.center_x,
                g.center_y,
                g.whitespace_before,
                g.whitespace_after,
                g.indent_left,
                g.indent_right,
                g.centeredness,
                g.column_hint,
                g.near_page_top,
                g.near_page_bottom
            from du_block_geometry g
            join du_blocks b on b.block_id = g.block_id
            where b.document_id = %s
            """,
            (doc_id,),
        )
        return self._rows_to_map(rows)

    def store_geometry_features(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_geometry (
                block_id,
                width,
                height,
                center_x,
                center_y,
                whitespace_before,
                whitespace_after,
                indent_left,
                indent_right,
                centeredness,
                column_hint,
                near_page_top,
                near_page_bottom
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                width = excluded.width,
                height = excluded.height,
                center_x = excluded.center_x,
                center_y = excluded.center_y,
                whitespace_before = excluded.whitespace_before,
                whitespace_after = excluded.whitespace_after,
                indent_left = excluded.indent_left,
                indent_right = excluded.indent_right,
                centeredness = excluded.centeredness,
                column_hint = excluded.column_hint,
                near_page_top = excluded.near_page_top,
                near_page_bottom = excluded.near_page_bottom,
                updated_at = now()
            """,
            [
                (
                    row["block_id"],
                    row.get("width"),
                    row.get("height"),
                    row.get("center_x"),
                    row.get("center_y"),
                    row.get("whitespace_before"),
                    row.get("whitespace_after"),
                    row.get("indent_left"),
                    row.get("indent_right"),
                    row.get("centeredness"),
                    row.get("column_hint"),
                    row.get("near_page_top"),
                    row.get("near_page_bottom"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # typography
    # -------------------------------------------------------------------------

    def fetch_typography_features(self, doc_id: str) -> dict[Any, dict]:
        rows = self._fetch_dicts(
            """
            select
                t.block_id,
                t.font_name,
                t.font_family,
                t.font_size,
                t.font_ratio,
                t.bold,
                t.italic,
                t.small_caps,
                t.all_caps,
                t.largest_on_page,
                t.larger_than_prev,
                t.larger_than_next,
                t.font_name_change_prev,
                t.font_name_change_next,
                t.font_size_change_prev,
                t.font_size_change_next,
                t.is_document_font_mode
            from du_block_typography t
            join du_blocks b on b.block_id = t.block_id
            where b.document_id = %s
            """,
            (doc_id,),
        )
        return self._rows_to_map(rows)

    def store_typography_features(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_typography (
                block_id,
                font_name,
                font_family,
                font_size,
                font_ratio,
                bold,
                italic,
                small_caps,
                all_caps,
                largest_on_page,
                larger_than_prev,
                larger_than_next,
                font_name_change_prev,
                font_name_change_next,
                font_size_change_prev,
                font_size_change_next,
                is_document_font_mode
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                font_name = excluded.font_name,
                font_family = excluded.font_family,
                font_size = excluded.font_size,
                font_ratio = excluded.font_ratio,
                bold = excluded.bold,
                italic = excluded.italic,
                small_caps = excluded.small_caps,
                all_caps = excluded.all_caps,
                largest_on_page = excluded.largest_on_page,
                larger_than_prev = excluded.larger_than_prev,
                larger_than_next = excluded.larger_than_next,
                font_name_change_prev = excluded.font_name_change_prev,
                font_name_change_next = excluded.font_name_change_next,
                font_size_change_prev = excluded.font_size_change_prev,
                font_size_change_next = excluded.font_size_change_next,
                is_document_font_mode = excluded.is_document_font_mode
            """,
            [
                (
                    row["block_id"],
                    row.get("font_name"),
                    row.get("font_family"),
                    row.get("font_size"),
                    row.get("font_ratio"),
                    row.get("bold"),
                    row.get("italic"),
                    row.get("small_caps"),
                    row.get("all_caps"),
                    row.get("largest_on_page"),
                    row.get("larger_than_prev"),
                    row.get("larger_than_next"),
                    row.get("font_name_change_prev"),
                    row.get("font_name_change_next"),
                    row.get("font_size_change_prev"),
                    row.get("font_size_change_next"),
                    row.get("is_document_font_mode"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # surface
    # -------------------------------------------------------------------------

    def fetch_surface_features(self, doc_id: str) -> dict[Any, dict]:
        rows = self._fetch_dicts(
            """
            select
                s.block_id,
                s.char_count,
                s.word_count,
                s.sentence_count,
                s.line_count,
                s.mean_line_length,
                s.line_width_ratio,
                s.capitalization_ratio,
                s.punctuation_density,
                s.digit_density,
                s.ends_with_period,
                s.ends_with_colon,
                s.starts_with_number,
                s.starts_with_bullet,
                s.contains_parentheses,
                s.contains_brackets,
                s.contains_url,
                s.contains_email,
                s.contains_doi,
                s.contains_year,
                s.is_all_caps,
                s.is_short_line
            from du_block_surface_features s
            join du_blocks b on b.block_id = s.block_id
            where b.document_id = %s
            """,
            (doc_id,),
        )
        return self._rows_to_map(rows)

    def store_surface_features(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_surface_features (
                block_id,
                char_count,
                word_count,
                sentence_count,
                line_count,
                mean_line_length,
                line_width_ratio,
                capitalization_ratio,
                punctuation_density,
                digit_density,
                ends_with_period,
                ends_with_colon,
                starts_with_number,
                starts_with_bullet,
                contains_parentheses,
                contains_brackets,
                contains_url,
                contains_email,
                contains_doi,
                contains_year,
                is_all_caps,
                is_short_line
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                char_count = excluded.char_count,
                word_count = excluded.word_count,
                sentence_count = excluded.sentence_count,
                line_count = excluded.line_count,
                mean_line_length = excluded.mean_line_length,
                line_width_ratio = excluded.line_width_ratio,
                capitalization_ratio = excluded.capitalization_ratio,
                punctuation_density = excluded.punctuation_density,
                digit_density = excluded.digit_density,
                ends_with_period = excluded.ends_with_period,
                ends_with_colon = excluded.ends_with_colon,
                starts_with_number = excluded.starts_with_number,
                starts_with_bullet = excluded.starts_with_bullet,
                contains_parentheses = excluded.contains_parentheses,
                contains_brackets = excluded.contains_brackets,
                contains_url = excluded.contains_url,
                contains_email = excluded.contains_email,
                contains_doi = excluded.contains_doi,
                contains_year = excluded.contains_year,
                is_all_caps = excluded.is_all_caps,
                is_short_line = excluded.is_short_line
            """,
            [
                (
                    row["block_id"],
                    row.get("char_count"),
                    row.get("word_count"),
                    row.get("sentence_count"),
                    row.get("line_count"),
                    row.get("mean_line_length"),
                    row.get("line_width_ratio"),
                    row.get("capitalization_ratio"),
                    row.get("punctuation_density"),
                    row.get("digit_density"),
                    row.get("ends_with_period"),
                    row.get("ends_with_colon"),
                    row.get("starts_with_number"),
                    row.get("starts_with_bullet"),
                    row.get("contains_parentheses"),
                    row.get("contains_brackets"),
                    row.get("contains_url"),
                    row.get("contains_email"),
                    row.get("contains_doi"),
                    row.get("contains_year"),
                    row.get("is_all_caps"),
                    row.get("is_short_line"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # context
    # -------------------------------------------------------------------------

    def fetch_context_features(self, doc_id: str) -> dict[Any, dict]:
        rows = self._fetch_dicts(
            """
            select
                c.block_id,
                c.doc_y_ratio,
                c.page_y_ratio,
                c.front_matter_score,
                c.body_score,
                c.back_matter_score
            from du_block_context c
            join du_blocks b on b.block_id = c.block_id
            where b.document_id = %s
            """,
            (doc_id,),
        )
        return self._rows_to_map(rows)

    def store_context_features(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_context (
                block_id,
                doc_y_ratio,
                page_y_ratio,
                front_matter_score,
                body_score,
                back_matter_score
            )
            values (%s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                doc_y_ratio = excluded.doc_y_ratio,
                page_y_ratio = excluded.page_y_ratio,
                front_matter_score = excluded.front_matter_score,
                body_score = excluded.body_score,
                back_matter_score = excluded.back_matter_score
            """,
            [
                (
                    row["block_id"],
                    row.get("doc_y_ratio"),
                    row.get("page_y_ratio"),
                    row.get("front_matter_score"),
                    row.get("body_score"),
                    row.get("back_matter_score"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # semantic micro
    # -------------------------------------------------------------------------

    def fetch_semantic_micro_features(self, doc_id: str) -> dict[Any, dict]:
        rows = self._fetch_dicts(
            """
            select
                s.block_id,
                s.is_abstract_marker,
                s.is_keywords_marker,
                s.is_references_marker,
                s.is_figure_marker,
                s.is_table_marker,
                s.is_appendix_marker,
                s.contains_doi,
                s.contains_year,
                s.contains_citation_bracket,
                s.contains_citation_author_year
            from du_block_semantic_micro s
            join du_blocks b on b.block_id = s.block_id
            where b.document_id = %s
            """,
            (doc_id,),
        )
        return self._rows_to_map(rows)

    def store_semantic_micro_features(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_semantic_micro (
                block_id,
                is_abstract_marker,
                is_keywords_marker,
                is_references_marker,
                is_figure_marker,
                is_table_marker,
                is_appendix_marker,
                contains_doi,
                contains_year,
                contains_citation_bracket,
                contains_citation_author_year
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                is_abstract_marker = excluded.is_abstract_marker,
                is_keywords_marker = excluded.is_keywords_marker,
                is_references_marker = excluded.is_references_marker,
                is_figure_marker = excluded.is_figure_marker,
                is_table_marker = excluded.is_table_marker,
                is_appendix_marker = excluded.is_appendix_marker,
                contains_doi = excluded.contains_doi,
                contains_year = excluded.contains_year,
                contains_citation_bracket = excluded.contains_citation_bracket,
                contains_citation_author_year = excluded.contains_citation_author_year
            """,
            [
                (
                    row["block_id"],
                    row.get("is_abstract_marker"),
                    row.get("is_keywords_marker"),
                    row.get("is_references_marker"),
                    row.get("is_figure_marker"),
                    row.get("is_table_marker"),
                    row.get("is_appendix_marker"),
                    row.get("contains_doi"),
                    row.get("contains_year"),
                    row.get("contains_citation_bracket"),
                    row.get("contains_citation_author_year"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # signals
    # -------------------------------------------------------------------------

    def fetch_block_signals(self, doc_id: str) -> dict[Any, dict]:
        rows = self._fetch_dicts(
            """
            select
                s.block_id,
                s.title_like,
                s.heading_like,
                s.running_text_like as body_like,
                s.reference_like,
                s.caption_like,
                s.noise_like
            from du_block_signals s
            where s.block_id in (
                select block_id
                from du_blocks
                where document_id = %s
            )
            """,
            (doc_id,),
        )
        return self._rows_to_map(rows)

    def store_block_signals(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_signals (
                block_id,
                title_like,
                heading_like,
                running_text_like,
                reference_like,
                caption_like,
                noise_like
            )
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                title_like = excluded.title_like,
                heading_like = excluded.heading_like,
                running_text_like = excluded.running_text_like,
                reference_like = excluded.reference_like,
                caption_like = excluded.caption_like,
                noise_like = excluded.noise_like,
                updated_at = now()
            """,
            [
                (
                    row["block_id"],
                    row.get("title_like"),
                    row.get("heading_like"),
                    row.get("body_like"),
                    row.get("reference_like"),
                    row.get("caption_like"),
                    row.get("noise_like"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # roles
    # -------------------------------------------------------------------------

    def fetch_block_roles(self, doc_id: str) -> list[dict]:
        return self._fetch_dicts(
            """
            select
                r.block_id,
                b.block_index,
                r.role,
                r.title_score,
                r.heading_score,
                r.body_score,
                r.reference_score,
                r.caption_score,
                r.noise_score
            from du_block_roles r
            join du_blocks b on b.block_id = r.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (doc_id,),
        )

    def store_block_roles(self, doc_id: str, rows: list[dict]) -> None:
        self._executemany(
            """
            insert into du_block_roles (
                block_id,
                role,
                title_score,
                heading_score,
                body_score,
                reference_score,
                caption_score,
                noise_score
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                role = excluded.role,
                title_score = excluded.title_score,
                heading_score = excluded.heading_score,
                body_score = excluded.body_score,
                reference_score = excluded.reference_score,
                caption_score = excluded.caption_score,
                noise_score = excluded.noise_score
            """,
            [
                (
                    row["block_id"],
                    row.get("role"),
                    row.get("title_score"),
                    row.get("heading_score"),
                    row.get("body_score"),
                    row.get("reference_score"),
                    row.get("caption_score"),
                    row.get("noise_score"),
                )
                for row in rows
            ],
        )

    # -------------------------------------------------------------------------
    # zones
    # -------------------------------------------------------------------------

    def fetch_zones(self, doc_id: str) -> list[dict]:
        return self._fetch_dicts(
            """
            select
                zone_type,
                start_block_index,
                end_block_index,
                confidence
            from du_semantic_zones
            where document_id = %s
            order by start_block_index
            """,
            (doc_id,),
        )

    def store_zones(self, doc_id: str, rows: list[dict]) -> None:
        with self.conn.cursor() as cur:
            cur.execute("delete from du_semantic_zones where document_id = %s", (doc_id,))
            cur.executemany(
                """
                insert into du_semantic_zones (
                    document_id,
                    zone_type,
                    start_block_index,
                    end_block_index,
                    confidence,
                    source
                )
                values (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        doc_id,
                        row.get("zone_type"),
                        row.get("start_block_index"),
                        row.get("end_block_index"),
                        row.get("confidence"),
                        "inference.zones",
                    )
                    for row in rows
                ],
            )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # section tree
    # -------------------------------------------------------------------------

    def fetch_section_tree(self, doc_id: str) -> list[dict]:
        return self._fetch_dicts(
            """
            select
                section_node_id,
                parent_section_node_id,
                heading_block_id,
                start_block_index,
                end_block_index,
                page_start,
                page_end,
                level,
                role,
                section_number,
                title,
                title_normalized,
                is_numbered,
                confidence,
                source
            from du_section_tree
            where document_id = %s
            order by section_node_id
            """,
            (doc_id,),
        )

    def store_section_tree(self, doc_id: str, rows: list[dict]) -> None:
        with self.conn.cursor() as cur:
            cur.execute("delete from du_section_tree where document_id = %s", (doc_id,))
            if rows:
                cur.executemany(
                    """
                    insert into du_section_tree (
                        document_id,
                        section_node_id,
                        parent_section_node_id,
                        heading_block_id,
                        start_block_index,
                        end_block_index,
                        page_start,
                        page_end,
                        level,
                        role,
                        section_number,
                        title,
                        title_normalized,
                        is_numbered,
                        confidence,
                        source
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            doc_id,
                            row.get("node_id"),
                            row.get("parent_id"),
                            row.get("heading_block_id"),
                            row.get("start_block_index"),
                            row.get("end_block_index"),
                            row.get("page_start"),
                            row.get("page_end"),
                            row.get("level"),
                            row.get("role"),
                            row.get("section_number"),
                            row.get("title"),
                            row.get("title_normalized"),
                            row.get("is_numbered"),
                            row.get("confidence"),
                            row.get("source"),
                        )
                        for row in rows
                    ],
                )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # document type
    # -------------------------------------------------------------------------

    def fetch_document_type(self, doc_id: str) -> str | None:
        decision = self.fetch_document_type_decision(doc_id)
        if not decision:
            return None
        return decision.get("du_document_type")

    def fetch_document_type_decision(self, doc_id: str) -> dict | None:
        rows = self._fetch_dicts(
            """
            select
                du_document_type,
                du_document_type_secondary,
                du_document_type_margin,
                du_document_type_confidence,
                du_document_type_ambiguous
            from documents
            where document_id = %s
            """,
            (doc_id,),
        )
        if not rows:
            return None
        return rows[0]

    def store_document_type(self, doc_id: str, doc_type: str) -> None:
        self.store_document_type_decision(
            doc_id=doc_id,
            primary_type=doc_type,
            secondary_type=None,
            margin=1.0,
            confidence=1.0,
            ambiguous=False,
        )

    def store_document_type_decision(
        self,
        doc_id: str,
        primary_type: str,
        secondary_type: str | None,
        margin: float,
        confidence: float,
        ambiguous: bool,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                update documents
                set
                    du_document_type = %s,
                    du_document_type_secondary = %s,
                    du_document_type_margin = %s,
                    du_document_type_confidence = %s,
                    du_document_type_ambiguous = %s
                where document_id = %s
                """,
                (
                    primary_type,
                    secondary_type,
                    float(margin),
                    float(confidence),
                    bool(ambiguous),
                    doc_id,
                ),
            )
        self.conn.commit()

    def fetch_document_type_scores(self, doc_id: str) -> list[dict]:
        return self._fetch_dicts(
            """
            select
                doc_type,
                score,
                weight,
                rank,
                source
            from du_document_type_scores
            where document_id = %s
            order by rank
            """,
            (doc_id,),
        )

    def store_document_type_scores(
        self,
        doc_id: str,
        scores: dict[str, float],
        weights: dict[str, float],
        ranked: list[tuple[str, float]],
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "delete from du_document_type_scores where document_id = %s",
                (doc_id,),
            )
            cur.executemany(
                """
                insert into du_document_type_scores (
                    document_id,
                    doc_type,
                    score,
                    weight,
                    rank,
                    source
                )
                values (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        doc_id,
                        doc_type,
                        float(score),
                        float(weights.get(doc_type, 0.0)),
                        rank,
                        "inference.document_type",
                    )
                    for rank, (doc_type, score) in enumerate(ranked, start=1)
                ],
            )
        self.conn.commit()

    # -------------------------------------------------------------------------
    # convenience
    # -------------------------------------------------------------------------

    def fetch_all_block_features(self, doc_id: str) -> dict[Any, dict]:
        blocks = self.fetch_blocks(doc_id)
        features: dict[Any, dict] = {
            row["block_id"]: {"block_id": row["block_id"]} for row in blocks
        }

        for source in (
            self.fetch_geometry_features(doc_id),
            self.fetch_typography_features(doc_id),
            self.fetch_surface_features(doc_id),
            self.fetch_context_features(doc_id),
            self.fetch_semantic_micro_features(doc_id),
        ):
            for block_id, row in source.items():
                features.setdefault(block_id, {"block_id": block_id}).update(row)

        return features

    # -------------------------------------------------------------------------
    # DU inspect helpers
    # -------------------------------------------------------------------------

    def fetch_zone_hypotheses(self, doc_id: str) -> list[dict]:
        return self._fetch_dicts(
            """
            select
                zone_type,
                start_block_index,
                end_block_index,
                score as confidence
            from du_zone_hypotheses
            where document_id = %s
            order by start_block_index
            """,
            (doc_id,),
        )

    def fetch_semantic_zones(self, doc_id: str) -> list[dict]:
        return self.fetch_zones(doc_id)

    def fetch_roles(self, doc_id: str) -> list[dict]:
        return self.fetch_block_roles(doc_id)
