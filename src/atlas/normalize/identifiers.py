from __future__ import annotations

import re

from atlas.db.connection import get_connection


DOI_PREFIX_RE = re.compile(r"^(https?://doi\.org/|doi:)", re.I)
ISBN_CLEAN_RE = re.compile(r"[^0-9Xx]")
ISSN_CLEAN_RE = re.compile(r"[^0-9Xx]")


def normalize_doi(value: str) -> str:
    value = value.strip()
    value = DOI_PREFIX_RE.sub("", value)
    value = value.rstrip(".,;)")
    return value.lower()


def normalize_isbn(value: str) -> str:
    return ISBN_CLEAN_RE.sub("", value).upper()


def normalize_issn(value: str) -> str:
    cleaned = ISSN_CLEAN_RE.sub("", value).upper()
    if len(cleaned) == 8:
        return f"{cleaned[:4]}-{cleaned[4:]}"
    return cleaned


def normalize_urn(value: str) -> str:
    return value.strip().lower().rstrip(".,;)")


def normalize_handle(value: str) -> str:
    return value.strip().lower().rstrip(".,;)")


def normalize_identifier(identifier_type: str, value: str) -> str:
    if identifier_type == "doi":
        return normalize_doi(value)
    if identifier_type == "isbn":
        return normalize_isbn(value)
    if identifier_type == "issn":
        return normalize_issn(value)
    if identifier_type == "urn":
        return normalize_urn(value)
    if identifier_type == "handle":
        return normalize_handle(value)
    return value.strip()


def normalize_identifiers() -> int:
    # Schema (migration 0002): id, document_id, identifier_type, identifier_value, source
    changed = 0

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, document_id, identifier_type, identifier_value FROM document_identifiers"
        )
        rows = cur.fetchall()

        for row_id, document_id, identifier_type, identifier_value in rows:
            new_value = normalize_identifier(identifier_type, identifier_value)
            if new_value == identifier_value:
                continue

            # Check if normalized value already exists for this document
            cur.execute(
                """
                SELECT id FROM document_identifiers
                WHERE document_id = ?
                  AND identifier_type = ?
                  AND identifier_value = ?
                  AND id != ?
                LIMIT 1
                """,
                (document_id, identifier_type, new_value, row_id),
            )
            if cur.fetchone():
                # Duplicate after normalization — remove this row
                cur.execute("DELETE FROM document_identifiers WHERE id = ?", (row_id,))
            else:
                cur.execute(
                    "UPDATE document_identifiers SET identifier_value = ? WHERE id = ?",
                    (new_value, row_id),
                )
            changed += 1

        conn.commit()
    return changed


def dedupe_identifiers() -> int:
    removed = 0

    with get_connection() as conn:
        cur = conn.cursor()
        # Find duplicate rows (same document_id, identifier_type, identifier_value)
        # keep the row with the lowest id
        cur.execute(
            """
            SELECT id FROM document_identifiers
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM document_identifiers
                GROUP BY document_id, identifier_type, identifier_value
            )
            """
        )
        duplicate_ids = [row[0] for row in cur.fetchall()]
        for row_id in duplicate_ids:
            cur.execute("DELETE FROM document_identifiers WHERE id = ?", (row_id,))
            removed += 1
        conn.commit()

    return removed
