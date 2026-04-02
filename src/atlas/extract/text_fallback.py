from __future__ import annotations

from pathlib import Path

from atlas.db.connection import get_connection
from atlas.extract.text_pdftotext import extract_text_pdftotext
from atlas.extract.text_pymupdf import store_extraction


def run_pdftotext_fallback() -> int:
    processed = 0

    with get_connection() as conn:
        cur = conn.cursor()
            cur.execute(
                """
                select
                    d.document_id,
                    d.file_path,
                    d.relative_path
                from documents d
                join lateral (
                    select text_length
                    from extracted_texts
                    where document_id = d.document_id
                    order by created_at desc
                    limit 1
                ) e on true
                where e.text_length = 0
                """
            )
            rows = cur.fetchall()

        for doc_id, file_path, _relative_path in rows:
            text, error = extract_text_pdftotext(Path(file_path))

            if not text:
                continue

            store_extraction(
                document_id=doc_id,
                extractor="pdftotext",
                text_full=text,
                text_length=len(text),
                nul_bytes_removed=0,
                extract_status="ok",
                extract_error=None,
            )
            processed += 1

    return processed
