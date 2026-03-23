from __future__ import annotations

import json
from typing import Any, Iterable

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class Repository:
    """
    Persistence adapter for the current Document Understanding pipeline.

    Design rules:
    - schema-facing only
    - no business logic
    - tolerate minor legacy key drift at the boundaries
    - do not assume a specific Python type for document_id
    """

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # ------------------------------------------------------------------
    # low-level helpers
    # ------------------------------------------------------------------

    def _fetch_all(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _fetch_one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))

    def _table_exists(self, table_name: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select exists (
                    select 1
                    from information_schema.tables
                    where table_schema = current_schema()
                      and table_name = %s
                )
                """,
                (table_name,),
            )
            row = cur.fetchone()
            return bool(row and row[0])

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select exists (
                    select 1
                    from information_schema.columns
                    where table_schema = current_schema()
                      and table_name = %s
                      and column_name = %s
                )
                """,
                (table_name, column_name),
            )
            row = cur.fetchone()
            return bool(row and row[0])

    @staticmethod
    def _get(row: Any, key: str, default: Any = None) -> Any:
        if row is None:
            return default
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    def _replace_document_table(
        self,
        table: str,
        document_id: Any,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL("delete from {} where document_id = %s").format(sql.Identifier(table)),
                (document_id,),
            )
            if rows:
                stmt = sql.SQL("insert into {} ({}) values ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    sql.SQL(", ").join(sql.Placeholder(c) for c in columns),
                )
                cur.executemany(stmt, rows)
        self.conn.commit()

    def _replace_block_table(
        self,
        table: str,
        document_id: Any,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    delete from {}
                    where block_id in (
                        select block_id from du_blocks where document_id = %s
                    )
                    """
                ).format(sql.Identifier(table)),
                (document_id,),
            )
            if rows:
                stmt = sql.SQL("insert into {} ({}) values ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    sql.SQL(", ").join(sql.Placeholder(c) for c in columns),
                )
                cur.executemany(stmt, rows)
        self.conn.commit()

    @staticmethod
    def _as_bool(value: Any) -> bool | None:
        if value is None:
            return None
        return bool(value)

    @staticmethod
    def _jsonable_ranked(ranked: Iterable[Any]) -> list[list[Any]]:
        out: list[list[Any]] = []
        for item in ranked:
            if isinstance(item, tuple):
                out.append(list(item))
            elif isinstance(item, list):
                out.append(item)
            else:
                out.append([item])
        return out

    @staticmethod
    def _loads_jsonish(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def delete_du_document(self, document_id: Any) -> None:
        """
        Clear DU-derived state for a document, but keep extraction inputs.

        Important: du_layout_lines and du_layout_spans are extraction-layer inputs
        for build_document() and must survive a DU rerun.
        """
        with self.conn.cursor() as cur:
            for table in (
                "du_section_tree",
                "du_heading_candidates",
                "du_document_model",
                "du_semantic_zones",
                "du_zone_hypotheses",
                "du_document_context",
                "du_pages",
            ):
                if self._table_exists(table):
                    cur.execute(
                        sql.SQL("delete from {} where document_id = %s").format(sql.Identifier(table)),
                        (document_id,),
                    )

            if self._table_exists("du_blocks"):
                cur.execute("delete from du_blocks where document_id = %s", (document_id,))

            if self._table_exists("documents"):
                reset_parts = []
                for col in (
                    "du_document_type",
                    "du_document_type_secondary",
                    "du_document_type_margin",
                    "du_document_type_confidence",
                    "du_document_type_ambiguous",
                    "du_document_type_scores",
                    "du_document_type_weights",
                    "du_document_type_ranked",
                ):
                    if self._column_exists("documents", col):
                        if col == "du_document_type_ambiguous":
                            reset_parts.append(sql.SQL("{} = false").format(sql.Identifier(col)))
                        else:
                            reset_parts.append(sql.SQL("{} = null").format(sql.Identifier(col)))

                if reset_parts:
                    cur.execute(
                        sql.SQL("update documents set {} where document_id = %s").format(
                            sql.SQL(", ").join(reset_parts)
                        ),
                        (document_id,),
                    )

        self.conn.commit()

    # ------------------------------------------------------------------
    # documents
    # ------------------------------------------------------------------

    def fetch_documents(self) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            select
                document_id,
                file_path,
                relative_path,
                file_name,
                title,
                du_document_type,
                du_document_type_secondary,
                du_document_type_margin,
                du_document_type_confidence,
                du_document_type_ambiguous
            from documents
            order by coalesce(relative_path, file_path, file_name), document_id
            """,
            (),
        )

    # ------------------------------------------------------------------
    # build_document inputs / outputs
    # ------------------------------------------------------------------

    def insert_document_context(self, ctx: Any) -> None:
        row = {
            "document_id": self._get(ctx, "document_id"),
            "source_kind": self._get(ctx, "source_kind"),
            "text_source": self._get(ctx, "text_source"),
            "geometry_source": self._get(ctx, "geometry_source"),
            "reading_order_source": self._get(ctx, "reading_order_source"),
            "has_native_text": bool(self._get(ctx, "has_native_text", False)),
            "has_reliable_geometry": bool(self._get(ctx, "has_reliable_geometry", False)),
            "has_reliable_reading_order": bool(self._get(ctx, "has_reliable_reading_order", False)),
            "text_confidence": self._get(ctx, "text_confidence"),
            "geometry_confidence": self._get(ctx, "geometry_confidence"),
            "reading_order_confidence": self._get(ctx, "reading_order_confidence"),
            "notes": self._get(ctx, "notes"),
        }
        self._replace_document_table(
            "du_document_context",
            row["document_id"],
            [row],
            [
                "document_id",
                "source_kind",
                "text_source",
                "geometry_source",
                "reading_order_source",
                "has_native_text",
                "has_reliable_geometry",
                "has_reliable_reading_order",
                "text_confidence",
                "geometry_confidence",
                "reading_order_confidence",
                "notes",
            ],
        )

    def insert_pages(self, pages: list[Any]) -> None:
        if not pages:
            return
        document_id = self._get(pages[0], "document_id")
        rows = []
        for page in pages:
            rows.append(
                {
                    "document_id": self._get(page, "document_id"),
                    "page_index": self._get(page, "page_index"),
                    "width": self._get(page, "width"),
                    "height": self._get(page, "height"),
                    "image_based": self._get(page, "image_based"),
                    "native_text_present": self._get(page, "native_text_present"),
                    "page_confidence": self._get(page, "page_confidence"),
                }
            )
        self._replace_document_table(
            "du_pages",
            document_id,
            rows,
            [
                "document_id",
                "page_index",
                "width",
                "height",
                "image_based",
                "native_text_present",
                "page_confidence",
            ],
        )

    def insert_blocks(self, blocks: list[Any]) -> None:
        if not blocks:
            return
        document_id = self._get(blocks[0], "document_id")
        rows = []
        for block in blocks:
            rows.append(
                {
                    "document_id": self._get(block, "document_id"),
                    "page_index": self._get(block, "page_index"),
                    "block_index": self._get(block, "block_index"),
                    "start_char": self._get(block, "start_char"),
                    "end_char": self._get(block, "end_char"),
                    "text": self._get(block, "text", "") or "",
                    "x0": self._get(block, "x0"),
                    "y0": self._get(block, "y0"),
                    "x1": self._get(block, "x1"),
                    "y1": self._get(block, "y1"),
                    "page_y0": self._get(block, "page_y0"),
                    "page_y1": self._get(block, "page_y1"),
                    "doc_y0": self._get(block, "doc_y0"),
                    "doc_y1": self._get(block, "doc_y1"),
                    "text_source": self._get(block, "text_source"),
                    "geometry_source": self._get(block, "geometry_source"),
                    "text_confidence": self._get(block, "text_confidence"),
                    "geometry_confidence": self._get(block, "geometry_confidence"),
                    "reading_order_confidence": self._get(block, "reading_order_confidence"),
                }
            )
        self._replace_document_table(
            "du_blocks",
            document_id,
            rows,
            [
                "document_id",
                "page_index",
                "block_index",
                "start_char",
                "end_char",
                "text",
                "x0",
                "y0",
                "x1",
                "y1",
                "page_y0",
                "page_y1",
                "doc_y0",
                "doc_y1",
                "text_source",
                "geometry_source",
                "text_confidence",
                "geometry_confidence",
                "reading_order_confidence",
            ],
        )

    def fetch_blocks(self, document_id: Any) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            select
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
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )

    def fetch_block_signals(self, document_id: str) -> dict[str, dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select
                    s.*
                from du_block_signals s
                join du_blocks b on b.block_id = s.block_id
                where b.document_id = %s
                """,
                (document_id,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            return {str(row["block_id"]): row for row in rows}

    def fetch_signals(self, document_id: Any) -> list[dict[str, Any]]:
        return self.fetch_block_signals(document_id)

    def store_block_signals(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "block_id": row.get("block_id"),
                    "title_like": row.get("title_like"),
                    "author_like": row.get("author_like"),
                    "affiliation_like": row.get("affiliation_like"),
                    "date_like": row.get("date_like"),
                    "running_text_like": row.get("running_text_like"),
                    "heading_like": row.get("heading_like"),
                    "list_like": row.get("list_like"),
                    "toc_like": row.get("toc_like"),
                    "reference_like": row.get("reference_like"),
                    "bibliographic_entry_like": row.get("bibliographic_entry_like"),
                    "caption_like": row.get("caption_like"),
                    "marker_like": row.get("marker_like"),
                    "parenthetical_citation_like": row.get("parenthetical_citation_like"),
                    "journal_meta_like": row.get("journal_meta_like"),
                    "artifact_like": row.get("artifact_like"),
                    "noise_like": row.get("noise_like"),
                    "map_label_like": row.get("map_label_like"),
                }
            )
        self._replace_block_table(
            "du_block_signals",
            document_id,
            normalized,
            [
                "block_id",
                "title_like",
                "author_like",
                "affiliation_like",
                "date_like",
                "running_text_like",
                "heading_like",
                "list_like",
                "toc_like",
                "reference_like",
                "bibliographic_entry_like",
                "caption_like",
                "marker_like",
                "parenthetical_citation_like",
                "journal_meta_like",
                "artifact_like",
                "noise_like",
                "map_label_like",
            ],
        )

    def store_context_features(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "block_id": row.get("block_id"),
                    "doc_y_ratio": row.get("doc_y_ratio"),
                    "page_y_ratio": row.get("page_y_ratio"),
                    "front_matter_score": row.get("front_matter_score"),
                    "body_score": row.get("body_score"),
                    "back_matter_score": row.get("back_matter_score"),
                }
            )
        self._replace_block_table(
            "du_block_context",
            document_id,
            normalized,
            [
                "block_id",
                "doc_y_ratio",
                "page_y_ratio",
                "front_matter_score",
                "body_score",
                "back_matter_score",
            ],
        )

    def store_surface_features(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "block_id": row.get("block_id"),
                    "char_count": row.get("char_count"),
                    "word_count": row.get("word_count"),
                    "sentence_count": row.get("sentence_count"),
                    "line_count": row.get("line_count"),
                    "mean_line_length": row.get("mean_line_length"),
                    "line_width_ratio": row.get("line_width_ratio"),
                    "capitalization_ratio": row.get("capitalization_ratio"),
                    "punctuation_density": row.get("punctuation_density"),
                    "digit_density": row.get("digit_density"),
                    "ends_with_period": self._as_bool(row.get("ends_with_period")),
                    "ends_with_colon": self._as_bool(row.get("ends_with_colon")),
                    "starts_with_number": self._as_bool(row.get("starts_with_number")),
                    "starts_with_bullet": self._as_bool(row.get("starts_with_bullet")),
                    "contains_parentheses": self._as_bool(row.get("contains_parentheses")),
                    "contains_brackets": self._as_bool(row.get("contains_brackets")),
                    "contains_url": self._as_bool(row.get("contains_url")),
                    "contains_email": self._as_bool(row.get("contains_email")),
                    "contains_doi": self._as_bool(row.get("contains_doi")),
                    "contains_year": self._as_bool(row.get("contains_year")),
                    "is_all_caps": self._as_bool(row.get("is_all_caps")),
                    "is_short_line": self._as_bool(row.get("is_short_line")),
                }
            )
        self._replace_block_table(
            "du_block_surface_features",
            document_id,
            normalized,
            [
                "block_id",
                "char_count",
                "word_count",
                "sentence_count",
                "line_count",
                "mean_line_length",
                "line_width_ratio",
                "capitalization_ratio",
                "punctuation_density",
                "digit_density",
                "ends_with_period",
                "ends_with_colon",
                "starts_with_number",
                "starts_with_bullet",
                "contains_parentheses",
                "contains_brackets",
                "contains_url",
                "contains_email",
                "contains_doi",
                "contains_year",
                "is_all_caps",
                "is_short_line",
            ],
        )

    def store_semantic_micro_features(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "block_id": row.get("block_id"),
                    "is_abstract_marker": self._as_bool(row.get("is_abstract_marker")),
                    "is_keywords_marker": self._as_bool(row.get("is_keywords_marker")),
                    "is_references_marker": self._as_bool(row.get("is_references_marker")),
                    "is_figure_marker": self._as_bool(row.get("is_figure_marker")),
                    "is_table_marker": self._as_bool(row.get("is_table_marker")),
                    "is_appendix_marker": self._as_bool(row.get("is_appendix_marker")),
                    "contains_doi": self._as_bool(row.get("contains_doi")),
                    "contains_year": self._as_bool(row.get("contains_year")),
                    "contains_citation_bracket": self._as_bool(row.get("contains_citation_bracket")),
                    "contains_citation_author_year": self._as_bool(row.get("contains_citation_author_year")),
                }
            )
        self._replace_block_table(
            "du_block_semantic_micro",
            document_id,
            normalized,
            [
                "block_id",
                "is_abstract_marker",
                "is_keywords_marker",
                "is_references_marker",
                "is_figure_marker",
                "is_table_marker",
                "is_appendix_marker",
                "contains_doi",
                "contains_year",
                "contains_citation_bracket",
                "contains_citation_author_year",
            ],
        )

    def fetch_block_roles(self, document_id: Any) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            select r.*
            from du_block_roles r
            join du_blocks b on b.block_id = r.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )

    def fetch_roles(self, document_id: Any) -> list[dict[str, Any]]:
        return self.fetch_block_roles(document_id)

    def store_block_roles(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "block_id": row.get("block_id"),
                    "role": row.get("role") or "body",
                    "title_score": row.get("title_score"),
                    "heading_score": row.get("heading_score"),
                    "body_score": row.get("body_score"),
                    "reference_score": row.get("reference_score"),
                    "caption_score": row.get("caption_score"),
                    "noise_score": row.get("noise_score"),
                }
            )
        self._replace_block_table(
            "du_block_roles",
            document_id,
            normalized,
            [
                "block_id",
                "role",
                "title_score",
                "heading_score",
                "body_score",
                "reference_score",
                "caption_score",
                "noise_score",
            ],
        )

    def store_roles(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        self.store_block_roles(document_id, rows)

    def store_consensus(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        self.store_block_roles(document_id, rows)

    def fetch_zone_hypotheses(self, document_id: Any) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            """
            select
                zone_hypothesis_id,
                document_id,
                zone_type,
                start_block_index,
                end_block_index,
                page_start,
                page_end,
                score,
                source,
                created_at
            from du_zone_hypotheses
            where document_id = %s
            order by start_block_index, end_block_index, zone_type
            """,
            (document_id,),
        )
        for row in rows:
            row["confidence"] = row.get("score")
        return rows

    def store_zone_hypotheses(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "document_id": document_id,
                    "zone_type": row.get("zone_type") or row.get("zone_label"),
                    "start_block_index": row.get("start_block_index"),
                    "end_block_index": row.get("end_block_index"),
                    "page_start": row.get("page_start") or row.get("start_page_num"),
                    "page_end": row.get("page_end") or row.get("end_page_num"),
                    "score": row.get("score") if row.get("score") is not None else row.get("confidence"),
                    "source": row.get("source") or "du.zone_hypotheses",
                }
            )
        self._replace_document_table(
            "du_zone_hypotheses",
            document_id,
            normalized,
            [
                "document_id",
                "zone_type",
                "start_block_index",
                "end_block_index",
                "page_start",
                "page_end",
                "score",
                "source",
            ],
        )

    def store_zone_memberships(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "block_id": row.get("block_id"),
                    "zone_type": row.get("zone_type") or row.get("zone_label"),
                    "membership": row.get("membership"),
                    "source": row.get("source") or "du.zone_memberships",
                }
            )
        self._replace_block_table(
            "du_block_zone_memberships",
            document_id,
            normalized,
            ["block_id", "zone_type", "membership", "source"],
        )

    def fetch_semantic_zones(self, document_id: Any) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            select
                semantic_zone_id,
                document_id,
                zone_type,
                start_block_index,
                end_block_index,
                page_start,
                page_end,
                confidence,
                source,
                created_at
            from du_semantic_zones
            where document_id = %s
            order by start_block_index, end_block_index, zone_type
            """,
            (document_id,),
        )

    def store_semantic_zones(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        for row in rows or []:
            normalized.append(
                {
                    "document_id": document_id,
                    "zone_type": row.get("zone_type") or row.get("zone_label"),
                    "start_block_index": row.get("start_block_index"),
                    "end_block_index": row.get("end_block_index"),
                    "page_start": row.get("page_start") or row.get("start_page_num"),
                    "page_end": row.get("page_end") or row.get("end_page_num"),
                    "confidence": row.get("confidence"),
                    "source": row.get("source") or "du.semantic_zones",
                }
            )
        self._replace_document_table(
            "du_semantic_zones",
            document_id,
            normalized,
            [
                "document_id",
                "zone_type",
                "start_block_index",
                "end_block_index",
                "page_start",
                "page_end",
                "confidence",
                "source",
            ],
        )

    def fetch_section_tree(self, document_id: Any) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
            select
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
                source,
                created_at,
                updated_at
            from du_section_tree
            where document_id = %s
            order by start_block_index, section_node_id
            """,
            (document_id,),
        )

    def store_section_tree(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        normalized = []
        seen_ids: set[int] = set()

        for i, row in enumerate(rows or [], start=1):
            node_id = row.get("section_node_id")
            if node_id is None:
                node_id = row.get("node_id")
            if node_id is None:
                node_id = i

            parent_id = row.get("parent_section_node_id")
            if parent_id is None:
                parent_id = row.get("parent_node_id")

            node_id = int(node_id)
            parent_id = int(parent_id) if parent_id is not None else None

            if node_id in seen_ids:
                raise ValueError(f"Duplicate section_node_id in section tree payload: {node_id}")
            seen_ids.add(node_id)

            normalized.append(
                {
                    "document_id": document_id,
                    "section_node_id": node_id,
                    "parent_section_node_id": parent_id,
                    "heading_block_id": row.get("heading_block_id") or row.get("block_id"),
                    "start_block_index": row.get("start_block_index", 0),
                    "end_block_index": row.get("end_block_index", row.get("start_block_index", 0)),
                    "page_start": row.get("page_start") if row.get("page_start") is not None else row.get("start_page_num"),
                    "page_end": row.get("page_end") if row.get("page_end") is not None else row.get("end_page_num"),
                    "level": row.get("level", 1),
                    "role": row.get("role") or "heading",
                    "section_number": row.get("section_number"),
                    "title": row.get("title") or row.get("title_text") or "",
                    "title_normalized": row.get("title_normalized") or row.get("title_text_normalized"),
                    "is_numbered": bool(row.get("is_numbered", False)),
                    "confidence": row.get("confidence"),
                    "source": row.get("source") or row.get("generator_version") or "du.section_tree",
                }
            )

        valid_ids = {row["section_node_id"] for row in normalized}
        for row in normalized:
            parent_id = row["parent_section_node_id"]
            if parent_id is not None and parent_id not in valid_ids:
                raise ValueError(
                    f"Invalid parent_section_node_id {parent_id} for section_node_id {row['section_node_id']}"
                )

        self._replace_document_table(
            "du_section_tree",
            document_id,
            normalized,
            [
                "document_id",
                "section_node_id",
                "parent_section_node_id",
                "heading_block_id",
                "start_block_index",
                "end_block_index",
                "page_start",
                "page_end",
                "level",
                "role",
                "section_number",
                "title",
                "title_normalized",
                "is_numbered",
                "confidence",
                "source",
            ],
        )

    def fetch_block_records(self, document_id: Any) -> list[dict[str, Any]]:
        """Return blocks joined with the DU signal layers needed for document-level inference."""
        return self._fetch_all(
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

                g.width,
                g.height,
                g.center_x,
                g.center_y,
                g.whitespace_before,
                g.whitespace_after,
                g.indent_left as geometry_indent_left,
                g.indent_right as geometry_indent_right,
                g.centeredness,
                g.column_hint,
                g.near_page_top,
                g.near_page_bottom,

                t.font_name,
                coalesce(t.font_family_normalized, t.font_family) as font_family,
                t.font_size,
                t.font_ratio,
                t.bold,
                t.italic,
                t.small_caps,
                t.all_caps as typography_all_caps,
                t.largest_on_page,
                t.larger_than_prev,
                t.larger_than_next,
                t.font_name_change_prev,
                t.font_name_change_next,
                t.font_size_change_prev,
                t.font_size_change_next,
                t.is_document_font_mode,
                t.dominant_font_share,
                t.font_size_delta_prev,
                t.font_size_delta_next,

                sf.char_count,
                sf.word_count,
                sf.sentence_count,
                sf.line_count,
                sf.mean_line_length,
                sf.line_width_ratio,
                sf.capitalization_ratio,
                sf.punctuation_density,
                sf.digit_density,
                sf.ends_with_period,
                sf.ends_with_colon,
                sf.starts_with_number,
                sf.starts_with_bullet,
                sf.contains_parentheses,
                sf.contains_brackets,
                sf.contains_url,
                sf.contains_email,
                sf.contains_doi,
                sf.contains_year,
                sf.is_all_caps as surface_all_caps,
                sf.is_short_line,

                c.doc_y_ratio,
                c.page_y_ratio,
                c.front_matter_score,
                c.body_score as context_body_score,
                c.back_matter_score,

                sm.is_abstract_marker,
                sm.is_keywords_marker,
                sm.is_references_marker,
                sm.is_figure_marker,
                sm.is_table_marker,
                sm.is_appendix_marker,
                sm.contains_doi as semantic_contains_doi,
                sm.contains_year as semantic_contains_year,
                sm.contains_citation_bracket,
                sm.contains_citation_author_year,

                pf.is_top_band,
                pf.is_bottom_band,
                pf.page_number_like,
                pf.running_header_like,
                pf.running_footer_like,
                pf.repeated_across_pages,
                pf.repeated_same_parity,
                pf.first_page_meta_like,

                s.title_like,
                s.author_like,
                s.affiliation_like,
                s.date_like,
                s.running_text_like,
                s.heading_like,
                s.list_like,
                s.toc_like,
                s.reference_like,
                s.bibliographic_entry_like,
                s.caption_like,
                s.marker_like,
                s.parenthetical_citation_like,
                s.journal_meta_like,
                s.artifact_like,
                s.noise_like,
                s.map_label_like,

                r.role,
                r.title_score,
                r.heading_score,
                r.body_score,
                r.reference_score,
                r.caption_score,
                r.noise_score
            from du_blocks b
            left join du_block_geometry g on g.block_id = b.block_id
            left join du_block_typography t on t.block_id = b.block_id
            left join du_block_surface_features sf on sf.block_id = b.block_id
            left join du_block_context c on c.block_id = b.block_id
            left join du_block_semantic_micro sm on sm.block_id = b.block_id
            left join du_block_page_furniture_signals pf on pf.block_id = b.block_id
            left join du_block_signals s on s.block_id = b.block_id
            left join du_block_roles r on r.block_id = b.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if isinstance(key, tuple):
                    safe_key = "|".join("" if part is None else str(part) for part in key)
                else:
                    safe_key = str(key)
                out[safe_key] = self._json_safe(item)
            return out
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        return value

    def fetch_document_model(self, document_id: Any) -> dict[str, Any] | None:
        if not self._table_exists("du_document_model"):
            return None
        row = self._fetch_one(
            """
            select
                document_id,
                body_font_family,
                body_font_size,
                style_clusters,
                heading_style_candidates,
                created_at,
                updated_at
            from du_document_model
            where document_id = %s
            """,
            (document_id,),
        )
        if row is None:
            return None
        row["style_clusters"] = self._loads_jsonish(row.get("style_clusters"))
        row["heading_style_candidates"] = self._loads_jsonish(row.get("heading_style_candidates"))
        return row

    def store_document_model(self, document_id: Any, model: dict[str, Any] | None) -> None:
        if not self._table_exists("du_document_model"):
            return
        payload = model or {}
        with self.conn.cursor() as cur:
            cur.execute("delete from du_document_model where document_id = %s", (document_id,))
            cur.execute(
                """
                insert into du_document_model (
                    document_id,
                    body_font_family,
                    body_font_size,
                    style_clusters,
                    heading_style_candidates
                )
                values (%s, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    payload.get("body_font_family"),
                    payload.get("body_font_size"),
                    json.dumps(self._json_safe(payload.get("style_clusters") or {})),
                    json.dumps(self._json_safe(payload.get("heading_style_candidates") or [])),
                ),
            )
        self.conn.commit()

    def fetch_heading_candidates(self, document_id: Any) -> list[dict[str, Any]]:
        if not self._table_exists("du_heading_candidates"):
            return []
        rows = self._fetch_all(
            """
            select
                h.heading_id,
                h.document_id,
                h.block_id,
                b.block_index,
                b.page_index,
                b.text,
                h.heading_score,
                h.level,
                h.is_title,
                h.created_at,
                h.updated_at
            from du_heading_candidates h
            join du_blocks b on b.block_id = h.block_id
            where h.document_id = %s
            order by b.block_index, h.heading_id
            """,
            (document_id,),
        )
        return rows

    def store_heading_candidates(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        if not self._table_exists("du_heading_candidates"):
            return
        with self.conn.cursor() as cur:
            cur.execute("delete from du_heading_candidates where document_id = %s", (document_id,))
            if rows:
                cur.executemany(
                    """
                    insert into du_heading_candidates (
                        document_id,
                        block_id,
                        heading_score,
                        level,
                        is_title
                    )
                    values (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            document_id,
                            row.get("block_id"),
                            row.get("heading_score"),
                            row.get("level"),
                            bool(row.get("is_title", False)),
                        )
                        for row in rows
                    ],
                )
        self.conn.commit()

    def store_document_type_decision(
        self,
        document_id: Any,
        *,
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
                set du_document_type = %s,
                    du_document_type_secondary = %s,
                    du_document_type_margin = %s,
                    du_document_type_confidence = %s,
                    du_document_type_ambiguous = %s
                where document_id = %s
                """,
                (
                    primary_type,
                    secondary_type,
                    margin,
                    confidence,
                    ambiguous,
                    document_id,
                ),
            )
        self.conn.commit()

    def fetch_document_type(self, document_id: Any) -> dict[str, Any] | None:
        return self._fetch_one(
            """
            select
                document_id,
                du_document_type as primary_type,
                du_document_type_secondary as secondary_type,
                du_document_type_margin as margin,
                du_document_type_confidence as confidence,
                du_document_type_ambiguous as ambiguous
            from documents
            where document_id = %s
            """,
            (document_id,),
        )

    def store_document_type_scores(
        self,
        document_id: Any,
        scores: dict[str, Any],
        weights: dict[str, Any],
        ranked: list[Any],
    ) -> None:
        optional_cols = [
            col
            for col in (
                "du_document_type_scores",
                "du_document_type_weights",
                "du_document_type_ranked",
            )
            if self._column_exists("documents", col)
        ]
        if not optional_cols:
            return

        assignments = []
        params: list[Any] = []
        if "du_document_type_scores" in optional_cols:
            assignments.append(sql.SQL("du_document_type_scores = %s"))
            params.append(json.dumps(scores))
        if "du_document_type_weights" in optional_cols:
            assignments.append(sql.SQL("du_document_type_weights = %s"))
            params.append(json.dumps(weights))
        if "du_document_type_ranked" in optional_cols:
            assignments.append(sql.SQL("du_document_type_ranked = %s"))
            params.append(json.dumps(self._jsonable_ranked(ranked)))
        params.append(document_id)

        with self.conn.cursor() as cur:
            cur.execute(
                sql.SQL("update documents set {} where document_id = %s").format(
                    sql.SQL(", ").join(assignments)
                ),
                tuple(params),
            )
        self.conn.commit()

    def fetch_document_type_scores(self, document_id: Any) -> list[dict[str, Any]]:
        row = self.fetch_document_type(document_id) or {}
        primary = row.get("primary_type")
        secondary = row.get("secondary_type")
        primary_conf = row.get("confidence")
        margin = row.get("margin")

        if self._column_exists("documents", "du_document_type_ranked"):
            raw = self._fetch_one(
                """
                select
                    du_document_type_scores,
                    du_document_type_weights,
                    du_document_type_ranked
                from documents
                where document_id = %s
                """,
                (document_id,),
            )
            if raw:
                scores = self._loads_jsonish(raw.get("du_document_type_scores")) or {}
                weights = self._loads_jsonish(raw.get("du_document_type_weights")) or {}
                ranked = self._loads_jsonish(raw.get("du_document_type_ranked")) or []
                out: list[dict[str, Any]] = []
                for idx, item in enumerate(ranked, start=1):
                    doc_type = None
                    score = None
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        doc_type = item[0]
                        score = item[1]
                    elif isinstance(item, str):
                        doc_type = item
                    if doc_type is None:
                        continue
                    out.append(
                        {
                            "rank": idx,
                            "doc_type": doc_type,
                            "score": float(score if score is not None else scores.get(doc_type, 0.0) or 0.0),
                            "weight": float(weights.get(doc_type, 0.0) or 0.0),
                        }
                    )
                if out:
                    return out

        out: list[dict[str, Any]] = []
        if primary is not None:
            out.append(
                {
                    "rank": 1,
                    "doc_type": primary,
                    "score": float(primary_conf or 0.0),
                    "weight": float(primary_conf or 0.0),
                }
            )
        if secondary is not None:
            secondary_weight = 0.0
            if primary_conf is not None and margin is not None:
                try:
                    secondary_weight = max(float(primary_conf) - float(margin), 0.0)
                except Exception:
                    secondary_weight = 0.0
            out.append(
                {
                    "rank": 2,
                    "doc_type": secondary,
                    "score": float(secondary_weight),
                    "weight": float(secondary_weight),
                }
            )
        return out

    def store_block_zones(self, document_id: Any, rows: list[dict[str, Any]]) -> None:
        if not self._table_exists("du_block_zones"):
            return

        normalized = []
        for row in rows or []:
            block_id = row.get("block_id")
            if not block_id:
                continue
            normalized.append(
                {
                    "block_id": block_id,
                    "zone": row.get("zone") or "body",
                    "zone_confidence": row.get("zone_confidence"),
                }
            )

        self._replace_block_table(
            "du_block_zones",
            document_id,
            normalized,
            ["block_id", "zone", "zone_confidence"],
        )

    def fetch_block_zones(self, document_id: Any) -> list[dict[str, Any]]:
        if not self._table_exists("du_block_zones"):
            return []

        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select
                    z.block_id,
                    z.zone,
                    z.zone_confidence
                from du_block_zones z
                join du_blocks b on b.block_id = z.block_id
                where b.document_id = %s
                order by b.block_index
                """,
                (document_id,),
            )
            return list(cur.fetchall() or [])
