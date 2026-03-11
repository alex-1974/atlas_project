from __future__ import annotations

import re
import uuid

from atlas.db.connection import get_connection


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
ISBN_RE = re.compile(r"\b97[89][- ]?\d[- ]?\d{2,5}[- ]?\d{2,7}[- ]?\d{1,7}[- ]?\d\b")
ISSN_RE = re.compile(r"\b\d{4}-\d{3}[\dX]\b", re.I)
HANDLE_RE = re.compile(r"\bhdl:\S+", re.I)
URN_RE = re.compile(r"\burn:\S+", re.I)


def scan_identifiers(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    for doi in DOI_RE.findall(text):
        results.append(("doi", doi))

    for isbn in ISBN_RE.findall(text):
        results.append(("isbn", isbn))

    for issn in ISSN_RE.findall(text):
        results.append(("issn", issn))

    for handle in HANDLE_RE.findall(text):
        results.append(("handle", handle))

    for urn in URN_RE.findall(text):
        results.append(("urn", urn))

    return results


def _insert_identifier(
    document_id: str,
    identifier_type: str,
    identifier_value: str,
    source: str,
) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into document_identifiers (
                    identifier_id,
                    document_id,
                    identifier_type,
                    identifier_value,
                    source
                )
                values (%s,%s,%s,%s,%s)
                on conflict (document_id, identifier_type, identifier_value) do nothing
                """,
                (
                    str(uuid.uuid4()),
                    document_id,
                    identifier_type,
                    identifier_value,
                    source,
                ),
            )
            return cur.rowcount == 1


def extract_identifiers_from_text() -> int:
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id,
                    e.text_full
                from documents d
                join lateral (
                    select text_full
                    from extracted_texts
                    where document_id = d.document_id
                      and extract_status = 'ok'
                    order by created_at desc
                    limit 1
                ) e on true
                where e.text_full is not null
                """
            )
            rows = cur.fetchall()

    for document_id, text_full in rows:
        ids = scan_identifiers(text_full)

        for identifier_type, identifier_value in ids:
            if _insert_identifier(
                document_id=document_id,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                source="text",
            ):
                inserted += 1

    return inserted


def extract_identifiers_from_pdf_metadata() -> int:
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    pm.document_id,
                    coalesce(pm.title, ''),
                    coalesce(pm.author, ''),
                    coalesce(pm.subject, ''),
                    coalesce(pm.keywords, '')
                from pdf_metadata pm
                """
            )
            rows = cur.fetchall()

    for document_id, title, author, subject, keywords in rows:
        blob = "\n".join([title, author, subject, keywords])

        ids = scan_identifiers(blob)

        for identifier_type, identifier_value in ids:
            if _insert_identifier(
                document_id=document_id,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                source="pdf_metadata",
            ):
                inserted += 1

    return inserted


def extract_identifiers_from_filename() -> int:
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    document_id,
                    file_name
                from documents
                """
            )
            rows = cur.fetchall()

    for document_id, file_name in rows:
        ids = scan_identifiers(file_name)

        for identifier_type, identifier_value in ids:
            if _insert_identifier(
                document_id=document_id,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                source="filename",
            ):
                inserted += 1

    return inserted


def extract_identifiers() -> dict[str, int]:
    text_count = extract_identifiers_from_text()
    metadata_count = extract_identifiers_from_pdf_metadata()
    filename_count = extract_identifiers_from_filename()

    return {
        "text": text_count,
        "pdf_metadata": metadata_count,
        "filename": filename_count,
        "total": text_count + metadata_count + filename_count,
    }
