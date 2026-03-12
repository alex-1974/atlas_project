from __future__ import annotations

from atlas.db.connection import get_connection


def _short(text: str | None, limit: int = 100) -> str:
    if not text:
        return "-"
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _resolve_document_path_column(cur) -> str:
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


def inspect_document_map(limit: int = 10, document_path_filter: str | None = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            path_col = _resolve_document_path_column(cur)

            if document_path_filter and path_col != "document_id":
                cur.execute(
                    f"""
                    select document_id, {path_col}
                    from documents
                    where {path_col} ilike %s
                    order by {path_col}
                    limit %s
                    """,
                    (f"%{document_path_filter}%", limit),
                )
            else:
                cur.execute(
                    f"""
                    select document_id, {path_col}
                    from documents
                    order by {path_col}
                    limit %s
                    """,
                    (limit,),
                )

            docs = cur.fetchall()

            if not docs:
                print("No matching documents.")
                return

            for document_id, path_value in docs:
                print()
                print(path_value)

                cur.execute(
                    """
                    select
                        b.block_index,
                        b.page_index,
                        b.text,

                        coalesce(s.title_like, 0.0) as title_like,
                        coalesce(s.author_like, 0.0) as author_like,
                        coalesce(s.affiliation_like, 0.0) as affiliation_like,
                        coalesce(s.date_like, 0.0) as date_like,
                        coalesce(s.running_text_like, 0.0) as running_text_like,
                        coalesce(s.heading_like, 0.0) as heading_like,
                        coalesce(s.toc_like, 0.0) as toc_like,
                        coalesce(s.reference_like, 0.0) as reference_like,
                        coalesce(s.caption_like, 0.0) as caption_like,
                        coalesce(s.journal_meta_like, 0.0) as journal_meta_like,
                        coalesce(s.artifact_like, 0.0) as artifact_like,

                        coalesce(g.centeredness, 0.0) as centeredness,
                        coalesce(g.near_page_top, 0.0) as near_page_top,

                        max(case when m.zone_type = 'header_candidate' then m.membership end) as header_m,
                        max(case when m.zone_type = 'body_candidate' then m.membership end) as body_m,
                        max(case when m.zone_type = 'toc_candidate' then m.membership end) as toc_m,
                        max(case when m.zone_type = 'references_candidate' then m.membership end) as ref_m
                    from du_blocks b
                    left join du_block_signals s on s.block_id = b.block_id
                    left join du_block_geometry g on g.block_id = b.block_id
                    left join du_block_zone_memberships m on m.block_id = b.block_id
                    where b.document_id = %s
                    group by
                        b.block_index,
                        b.page_index,
                        b.text,
                        s.title_like,
                        s.author_like,
                        s.affiliation_like,
                        s.date_like,
                        s.running_text_like,
                        s.heading_like,
                        s.toc_like,
                        s.reference_like,
                        s.caption_like,
                        s.journal_meta_like,
                        s.artifact_like,
                        g.centeredness,
                        g.near_page_top
                    order by b.block_index
                    limit 40
                    """,
                    (document_id,),
                )

                blocks = cur.fetchall()

                cur.execute(
                    """
                    select zone_type, start_block_index, end_block_index, confidence
                    from du_semantic_zones
                    where document_id = %s
                    order by start_block_index
                    """,
                    (document_id,),
                )

                zones = cur.fetchall()

                if zones:
                    print("  semantic zones:")
                    for zone_type, start_idx, end_idx, confidence in zones:
                        conf = 0.0 if confidence is None else confidence
                        print(
                            f"    {zone_type:12s} "
                            f"{start_idx:>4d}-{end_idx:<4d} "
                            f"conf={conf:.2f}"
                        )
                else:
                    print("  semantic zones: -")

                print("  blocks:")

                for row in blocks:
                    (
                        block_index,
                        page_index,
                        text,
                        title_like,
                        author_like,
                        affiliation_like,
                        date_like,
                        running_text_like,
                        heading_like,
                        toc_like,
                        reference_like,
                        caption_like,
                        journal_meta_like,
                        artifact_like,
                        centeredness,
                        near_page_top,
                        header_m,
                        body_m,
                        toc_m,
                        ref_m,
                    ) = row

                    print(
                        f"    [{block_index:>3d}] "
                        f"p={page_index:<2d} "
                        f"T={title_like:.2f} "
                        f"A={author_like:.2f} "
                        f"Aff={affiliation_like:.2f} "
                        f"D={date_like:.2f} "
                        f"Run={running_text_like:.2f} "
                        f"Hd={heading_like:.2f} "
                        f"TOC={toc_like:.2f} "
                        f"Ref={reference_like:.2f} "
                        f"Cap={caption_like:.2f} "
                        f"J={journal_meta_like:.2f} "
                        f"Art={artifact_like:.2f} "
                        f"C={centeredness:.2f} "
                        f"Top={near_page_top:.2f} "
                        f"HM={float(header_m or 0):.2f} "
                        f"BM={float(body_m or 0):.2f} "
                        f"TM={float(toc_m or 0):.2f} "
                        f"RM={float(ref_m or 0):.2f}"
                    )
                    print(f"          {_short(text)}")
