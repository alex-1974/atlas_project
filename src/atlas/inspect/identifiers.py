from __future__ import annotations

from atlas.db.connection import get_connection


def get_identifier_summary():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select identifier_type, count(*)
                from document_identifiers
                group by identifier_type
                order by identifier_type
                """
            )
            return cur.fetchall()


def get_identifier_sources():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select source, identifier_type, count(*)
                from document_identifiers
                group by source, identifier_type
                order by source, identifier_type
                """
            )
            return cur.fetchall()


def get_identifier_examples(limit: int = 50):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.relative_path,
                    di.identifier_type,
                    di.identifier_value,
                    di.source
                from document_identifiers di
                join documents d on d.document_id = di.document_id
                order by di.identifier_type, di.source, d.relative_path
                limit %s
                """,
                (limit,),
            )
            return cur.fetchall()
