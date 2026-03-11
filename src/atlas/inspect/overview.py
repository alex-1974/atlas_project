from __future__ import annotations

from atlas.db.connection import get_connection


def get_overview(limit: int = 50):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    top_category,
                    relative_path,
                    coalesce(title, 'NO_TITLE') as title,
                    coalesce(text_quality, 'NO_QUALITY') as text_quality,
                    page_count
                from documents
                order by top_category, relative_path
                limit %s
                """,
                (limit,),
            )
            return cur.fetchall()
