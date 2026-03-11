from __future__ import annotations

from atlas.db.connection import get_connection


def get_state_summary():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    doc_state,
                    count(*)
                from documents
                group by doc_state
                order by doc_state
                """
            )
            return cur.fetchall()
