from __future__ import annotations

from atlas.db.connection import get_connection


def get_empty_or_poor(limit: int = 100):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.top_category,
                    d.relative_path,
                    coalesce(d.title, 'NO_TITLE') as title,
                    coalesce(d.text_quality, 'NO_QUALITY') as text_quality,
                    d.page_count,
                    e.text_length
                from documents d
                join lateral (
                    select text_length
                    from extracted_texts
                    where document_id = d.document_id
                    order by created_at desc
                    limit 1
                ) e on true
                where d.text_quality in ('empty', 'very_poor', 'poor')
                order by d.top_category, d.relative_path
                limit %s
                """,
                (limit,),
            )
            return cur.fetchall()
