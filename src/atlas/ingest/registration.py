from __future__ import annotations

import uuid

import fitz

from atlas.common.hashing import sha256_file
from atlas.db.connection import get_connection
from atlas.models.records import DiscoveredPdf


def _get_page_count(path) -> int | None:
    try:
        with fitz.open(path) as doc:
            return len(doc)
    except Exception:
        return None


def register_document(discovered: DiscoveredPdf) -> str:
    path = discovered.absolute_path
    file_hash = sha256_file(path)
    page_count = _get_page_count(path)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select document_id
                from documents
                where file_hash = %s
                """,
                (file_hash,),
            )
            row = cur.fetchone()
            if row:
                return row[0]

            document_id = str(uuid.uuid4())

            cur.execute(
                """
                insert into documents (
                    document_id,
                    file_hash,
                    file_path,
                    relative_path,
                    file_name,
                    file_size,
                    top_category,
                    is_review_bucket,
                    is_duplicate_bucket,
                    page_count
                )
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    document_id,
                    file_hash,
                    str(path),
                    str(discovered.relative_path),
                    path.name,
                    path.stat().st_size,
                    discovered.top_category,
                    discovered.is_review_bucket,
                    discovered.is_duplicate_bucket,
                    page_count,
                ),
            )

            return document_id
