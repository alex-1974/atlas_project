from __future__ import annotations

import re

from atlas.db.connection import get_connection


def classify_text_quality(text: str | None) -> str:
    if not text:
        return "empty"

    length = len(text)
    if length < 200:
        return "very_poor"
    if length < 1000:
        return "poor"

    weird_ratio = len(re.findall(r"[^\w\s\.,;:!?()\[\]\-/'\"%&]", text)) / max(1, length)

    if weird_ratio > 0.20:
        return "poor"
    if weird_ratio > 0.10:
        return "mixed"

    return "good"


def enrich_text_quality() -> int:
    updated = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select d.document_id, e.text_full
                from documents d
                join lateral (
                    select text_full
                    from extracted_texts
                    where document_id = d.document_id
                      and extract_status = 'ok'
                    order by created_at desc
                    limit 1
                ) e on true
                where d.text_quality is null
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, text_full in rows:
                quality = classify_text_quality(text_full)
                cur.execute(
                    """
                    update documents
                    set text_quality = %s
                    where document_id = %s
                    """,
                    (quality, document_id),
                )
                updated += 1

    return updated
