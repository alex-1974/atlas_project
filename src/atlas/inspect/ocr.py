from __future__ import annotations

from atlas.db.connection import get_connection


def get_ocr_candidates(limit: int = 100):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    top_category,
                    relative_path,
                    coalesce(title, 'NO_TITLE') as title,
                    page_count
                from documents
                where needs_ocr = true
                order by top_category, relative_path
                limit %s
                """,
                (limit,),
            )
            return cur.fetchall()
