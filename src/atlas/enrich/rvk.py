# src/atlas/catalog/update.py
"""atlas update — detect and index new PDFs in the catalog folder.

Scans the catalog root recursively for PDFs that are not yet in the
database and indexes them via add_document().

Returns:
    {"new": int, "skipped": int, "failed": int,
     "errors": list[tuple[str, str]]}
"""
from __future__ import annotations

import logging
from pathlib import Path

from atlas.db.connection import connect
from atlas.db.migrate import assert_schema_current
from atlas.catalog.add import add_document, _hash_file

log = logging.getLogger(__name__)


def update_catalog(catalog_root: Path) -> dict:
    """Scan catalog root for new PDFs and index them.

    Skips PDFs already in the database (by SHA-256 hash).
    Does not re-process failed documents — use atlas dev du process for that.

    Returns:
        {"new": int, "skipped": int, "failed": int,
         "errors": list[tuple[str, str]]}
    """
    db_path = catalog_root / ".atlas" / "catalog.db"
    conn    = connect(db_path)
    assert_schema_current(conn)

    # Build set of known document_ids
    known_ids: set[str] = {
        row["document_id"]
        for row in conn.execute("SELECT document_id FROM documents").fetchall()
    }
    conn.close()

    # Scan for PDFs — skip .atlas/ itself
    atlas_dir = catalog_root / ".atlas"
    pdfs = [
        p for p in catalog_root.rglob("*.pdf")
        if not p.is_relative_to(atlas_dir)
    ]

    new_count = skipped = failed = 0
    errors: list[tuple[str, str]] = []

    for pdf in sorted(pdfs):
        try:
            doc_id = _hash_file(pdf)
        except Exception as exc:
            failed += 1
            errors.append((pdf.name, f"Hash-Fehler: {exc}"))
            continue

        if doc_id in known_ids:
            skipped += 1
            continue

        try:
            result = add_document(catalog_root, pdf)
            if result["skipped"]:
                skipped += 1
            else:
                new_count += 1
                known_ids.add(doc_id)
                log.info("Indexed: %s", pdf.name)
        except Exception as exc:
            failed += 1
            errors.append((pdf.name, str(exc)))
            log.error("Failed: %s — %s", pdf.name, exc)

    return {
        "new":     new_count,
        "skipped": skipped,
        "failed":  failed,
        "errors":  errors,
    }
