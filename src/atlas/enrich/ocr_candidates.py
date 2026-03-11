from atlas.db.connection import get_connection


def mark_ocr_candidates() -> int:
    updated = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id
                from documents d
                join lateral (
                    select
                        text_length,
                        extractor,
                        extract_status
                    from extracted_texts
                    where document_id = d.document_id
                    order by created_at desc
                    limit 1
                ) e on true
                where coalesce(e.text_length, 0) = 0
                  and e.extract_status = 'ok'
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for (document_id,) in rows:
                cur.execute(
                    """
                    update documents
                    set has_text_layer = false,
                        needs_ocr = true
                    where document_id = %s
                    """,
                    (document_id,),
                )
                updated += 1

        with conn.cursor() as cur:
            cur.execute(
                """
                update documents
                set has_text_layer = true,
                    needs_ocr = false
                where document_id in (
                    select d.document_id
                    from documents d
                    join lateral (
                        select text_length
                        from extracted_texts
                        where document_id = d.document_id
                        order by created_at desc
                        limit 1
                    ) e on true
                    where coalesce(e.text_length, 0) > 0
                )
                """
            )

    return updated
