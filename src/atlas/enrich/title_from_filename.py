from pathlib import Path
import re

from atlas.db.connection import get_connection


def guess_title_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem

    # doppelte Unterstriche oft als Trenner behandeln
    if "__" in stem:
        stem = stem.split("__", 1)[1]

    # Hash-artige Enden entfernen
    stem = re.sub(r"__[0-9a-f]{6,}$", "", stem, flags=re.IGNORECASE)

    # führende Länderkürzel / grobe Marker entfernen
    stem = re.sub(
        r"^(DE|UK|FR|EU|INT|AT|CH|US)_(?=[A-Za-z])",
        "",
        stem,
        flags=re.IGNORECASE,
    )

    # Jahreszahlen im Mittelteil nicht blind entfernen; nur schön formatieren
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip()

    if len(stem) < 5:
        return None
    if re.fullmatch(r"[\d\-\_ ]+", stem):
        return None
    
    return stem


def enrich_titles_from_filename() -> int:
    updated = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select document_id, file_name
                from documents
                where title is null
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, file_name in rows:
                title = guess_title_from_filename(file_name)
                if title:
                    cur.execute(
                        """
                        update documents
                        set title = %s,
                            title_source = 'filename_fallback'
                        where document_id = %s
                        """,
                        (title, document_id),
                    )
                    updated += 1

    return updated
