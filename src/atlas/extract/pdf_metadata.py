from __future__ import annotations

import uuid
from pathlib import Path

import fitz
from psycopg.types.json import Json

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
        "raw": meta,
    }


def extract_pdf_metadata() -> int:
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select d.document_id, d.file_path
                from documents d
                left join pdf_metadata pm on pm.document_id = d.document_id
                where pm.document_id is null
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, file_path in rows:
                meta = read_metadata(Path(file_path))
                if not meta:
                    continue

                cur.execute(
                    """
                    insert into pdf_metadata (
                        metadata_id,
                        document_id,
                        title,
                        author,
                        subject,
                        keywords,
                        creator,
                        producer,
                        creation_date,
                        mod_date,
                        raw_json
                    )
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        str(uuid.uuid4()),
                        document_id,
                        meta["title"],
                        meta["author"],
                        meta["subject"],
                        meta["keywords"],
                        meta["creator"],
                        meta["producer"],
                        meta["creation_date"],
                        meta["mod_date"],
                        Json(meta["raw"]),
                    ),
                )
                inserted += 1

    return inserted
