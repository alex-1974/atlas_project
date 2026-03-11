from __future__ import annotations

import re

from atlas.db.connection import get_connection


BAD_PATTERNS = [
    r"^microsoft word",
    r"^adobe",
    r"^scan",
    r"^untitled",
]


def is_plausible_title(title: str | None) -> bool:
    if not title:
        return False

    title = title.strip()

    if len(title) < 8:
        return False
    if len(title) > 250:
        return False
    if re.match(r"^[0-9\s\-]+$", title):
        return False

    lower = title.lower()
    for pat in BAD_PATTERNS:
        if re.match(pat, lower):
            return False

    return True


def enrich_titles_from_pdf_metadata() -> int:
    updated = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id,
                    d.title,
                    d.title_source,
                    pm.title
                from documents d
                join pdf_metadata pm on pm.document_id = d.document_id
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, current_title, source, meta_title in rows:
                if not is_plausible_title(meta_title):
                    continue

                replace = False
                if current_title is None:
                    replace = True
                elif source in ("filename", "text_heuristic", "unknown", None):
                    replace = True

                if not replace:
                    continue

                cur.execute(
                    """
                    update documents
                    set title = %s,
                        title_source = 'pdf_metadata'
                    where document_id = %s
                    """,
                    (meta_title.strip(), document_id),
                )
                updated += 1

    return updated
