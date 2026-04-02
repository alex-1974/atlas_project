from __future__ import annotations

from pathlib import Path

import fitz

from atlas.db.connection import get_connection


def read_metadata(path: Path) -> dict | None:
    try:
        with fitz.open(path) as doc:
            meta = doc.metadata or {}
    except Exception:
        return None
    return {
        "title": meta.get("title"),
        "author": meta.get("author"),
        "subject": meta.get("subject"),
        "keywords": meta.get("keywords"),
        "creator": meta.get("creator"),
        "producer": meta.get("producer"),
        "creation_date": meta.get("creationDate"),
        "mod_date": meta.get("modDate"),
    }


def extract_pdf_metadata() -> int:
    # Schema (migration 0002): extracted_metadata
    # Columns: document_id, method, pdf_title, pdf_author, pdf_subject,
    #          pdf_keywords, pdf_creator, pdf_producer,
    #          pdf_creation_date_raw, pdf_mod_date_raw
    inserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.document_id, d.file_path
            FROM documents d
            LEFT JOIN extracted_metadata em ON em.document_id = d.document_id
            WHERE em.document_id IS NULL
            """
        )
        rows = cur.fetchall()

        for document_id, file_path in rows:
            meta = read_metadata(Path(file_path))
            if not meta:
                continue
            cur.execute(
                """
                INSERT OR REPLACE INTO extracted_metadata (
                    document_id,
                    method,
                    pdf_title,
                    pdf_author,
                    pdf_subject,
                    pdf_keywords,
                    pdf_creator,
                    pdf_producer,
                    pdf_creation_date_raw,
                    pdf_mod_date_raw
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    "pymupdf",
                    meta["title"],
                    meta["author"],
                    meta["subject"],
                    meta["keywords"],
                    meta["creator"],
                    meta["producer"],
                    meta["creation_date"],
                    meta["mod_date"],
                ),
            )
            inserted += 1

        conn.commit()
    return inserted
