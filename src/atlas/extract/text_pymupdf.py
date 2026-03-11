from __future__ import annotations

import uuid
from pathlib import Path

import fitz

from atlas.db.connection import get_connection


def _sanitize_text(text: str) -> tuple[str, int]:
    if not text:
        return "", 0
    nul_count = text.count("\x00")
    return text.replace("\x00", ""), nul_count


def already_extracted(document_id: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from extracted_texts
                where document_id = %s
                  and extract_status = 'ok'
                limit 1
                """,
                (document_id,),
            )
            return cur.fetchone() is not None


def store_extraction(
    document_id: str,
    extractor: str,
    text_full: str | None,
    text_length: int | None,
    nul_bytes_removed: int,
    extract_status: str,
    extract_error: str | None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into extracted_texts (
                    extraction_id,
                    document_id,
                    extractor,
                    text_full,
                    text_length,
                    nul_bytes_removed,
                    extract_status,
                    extract_error
                )
                values (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    str(uuid.uuid4()),
                    document_id,
                    extractor,
                    text_full,
                    text_length,
                    nul_bytes_removed,
                    extract_status,
                    extract_error,
                ),
            )


def extract_text_pymupdf(path: Path, document_id: str, force: bool = False) -> dict:
    if not force and already_extracted(document_id):
        return {
            "status": "skipped",
            "reason": "already_extracted",
            "nul_bytes_removed": 0,
            "text_length": None,
        }

    try:
        with fitz.open(path) as doc:
            parts: list[str] = []
            for page in doc:
                parts.append(page.get_text() or "")

        raw_text = "".join(parts)
        text, nul_count = _sanitize_text(raw_text)

        store_extraction(
            document_id=document_id,
            extractor="pymupdf",
            text_full=text,
            text_length=len(text),
            nul_bytes_removed=nul_count,
            extract_status="ok",
            extract_error=None,
        )

        return {
            "status": "ok",
            "nul_bytes_removed": nul_count,
            "text_length": len(text),
        }

    except Exception as exc:
        store_extraction(
            document_id=document_id,
            extractor="pymupdf",
            text_full=None,
            text_length=None,
            nul_bytes_removed=0,
            extract_status="error",
            extract_error=f"{type(exc).__name__}: {exc}",
        )

        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "nul_bytes_removed": 0,
            "text_length": None,
        }
