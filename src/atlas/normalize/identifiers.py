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
    changed = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select identifier_id, document_id, identifier_type, identifier_value
                from document_identifiers
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for identifier_id, document_id, identifier_type, identifier_value in rows:
                new_value = normalize_identifier(identifier_type, identifier_value)

                if new_value == identifier_value:
                    continue

                # Prüfen, ob der normalisierte Zielwert im selben Dokument schon existiert
                cur.execute(
                    """
                    select identifier_id
                    from document_identifiers
                    where document_id = %s
                      and identifier_type = %s
                      and identifier_value = %s
                      and identifier_id <> %s
                    limit 1
                    """,
                    (document_id, identifier_type, new_value, identifier_id),
                )
                existing = cur.fetchone()

                if existing:
                    # Zielwert existiert schon -> diesen Datensatz löschen
                    cur.execute(
                        """
                        delete from document_identifiers
                        where identifier_id = %s
                        """,
                        (identifier_id,),
                    )
                    changed += 1
                    continue

                cur.execute(
                    """
                    update document_identifiers
                    set identifier_value = %s
                    where identifier_id = %s
                    """,
                    (new_value, identifier_id),
                )
                changed += 1

    return changed


def dedupe_identifiers() -> int:
    removed = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from document_identifiers a
                using document_identifiers b
                where a.identifier_id < b.identifier_id
                  and a.document_id = b.document_id
                  and a.identifier_type = b.identifier_type
                  and a.identifier_value = b.identifier_value
                returning a.identifier_id
                """
            )
            removed = len(cur.fetchall())

    return removed
