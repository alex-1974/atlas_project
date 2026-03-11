from __future__ import annotations

from atlas.db.connection import get_connection


def classify_documents() -> int:
    updated = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id,
                    e.text_length,
                    e.extractor
                from documents d
                join lateral (
                    select text_length, extractor
                    from extracted_texts
                    where document_id = d.document_id
                    order by created_at desc
                    limit 1
                ) e on true
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, text_length, extractor in rows:
                if text_length and text_length > 0:
                    if extractor == "pymupdf":
                        state = "text_pdf"
                    else:
                        state = "fallback_text_pdf"
                    has_text_layer = True
                    needs_ocr = False
                else:
                    state = "ocr_candidate"
                    has_text_layer = False
                    needs_ocr = True

                cur.execute(
                    """
                    update documents
                    set doc_state = %s,
                        has_text_layer = %s,
                        needs_ocr = %s
                    where document_id = %s
                    """,
                    (state, has_text_layer, needs_ocr, document_id),
                )
                updated += 1

    return updated
