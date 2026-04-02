from __future__ import annotations

import re

from atlas.db.connection import get_connection


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
ISBN_RE = re.compile(r"\b97[89][- ]?\d[- ]?\d{2,5}[- ]?\d{2,7}[- ]?\d{1,7}[- ]?\d\b")
ISSN_RE = re.compile(r"\b\d{4}-\d{3}[\dX]\b", re.I)
ARXIV_RE = re.compile(r"\barxiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.I)
PMID_RE = re.compile(r"\bPMID[:\s]+(\d{6,8})\b")


def scan_identifiers(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for doi in DOI_RE.findall(text):
        key = ("doi", doi.rstrip("."))
        if key not in seen:
            seen.add(key)
            results.append(key)

    for isbn in ISBN_RE.findall(text):
        key = ("isbn", isbn)
        if key not in seen:
            seen.add(key)
            results.append(key)

    for issn in ISSN_RE.findall(text):
        key = ("issn", issn)
        if key not in seen:
            seen.add(key)
            results.append(key)

    for arxiv_id in ARXIV_RE.findall(text):
        key = ("arxiv_id", arxiv_id)
        if key not in seen:
            seen.add(key)
            results.append(key)

    for pmid in PMID_RE.findall(text):
        key = ("pmid", pmid)
        if key not in seen:
            seen.add(key)
            results.append(key)

    return results


def _insert_identifier(
    conn,
    document_id: str,
    identifier_type: str,
    identifier_value: str,
    source: str,
) -> bool:
    # Schema (migration 0002): document_id, identifier_type, identifier_value, source
    # UNIQUE(document_id, identifier_type, identifier_value, source)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO document_identifiers
            (document_id, identifier_type, identifier_value, source)
        VALUES (?, ?, ?, ?)
        """,
        (document_id, identifier_type, identifier_value, source),
    )
    return cur.rowcount == 1


def extract_identifiers_from_text() -> int:
    inserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT document_id, text
            FROM extracted_texts
            WHERE text IS NOT NULL
            """
        )
        rows = cur.fetchall()
        for document_id, text in rows:
            for identifier_type, identifier_value in scan_identifiers(text):
                if _insert_identifier(conn, document_id, identifier_type, identifier_value, "text"):
                    inserted += 1
        conn.commit()
    return inserted


def extract_identifiers_from_pdf_metadata() -> int:
    inserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT document_id,
                   coalesce(pdf_title, ''),
                   coalesce(pdf_author, ''),
                   coalesce(pdf_subject, ''),
                   coalesce(pdf_keywords, '')
            FROM extracted_metadata
            """
        )
        rows = cur.fetchall()
        for document_id, title, author, subject, keywords in rows:
            blob = "\n".join([title, author, subject, keywords])
            for identifier_type, identifier_value in scan_identifiers(blob):
                if _insert_identifier(conn, document_id, identifier_type, identifier_value, "pdf_metadata"):
                    inserted += 1
        conn.commit()
    return inserted


def extract_identifiers_from_filename() -> int:
    inserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT document_id, file_name FROM documents")
        rows = cur.fetchall()
        for document_id, file_name in rows:
            if not file_name:
                continue
            for identifier_type, identifier_value in scan_identifiers(file_name):
                if _insert_identifier(conn, document_id, identifier_type, identifier_value, "filename"):
                    inserted += 1
        conn.commit()
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
