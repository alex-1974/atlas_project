"""
atlas.catalog.move

atlas mv — Dokument verschieben und DB aktualisieren.

move_document(root, source, dest) verschiebt ein PDF und
aktualisiert file_path + file_name in der DB atomisch.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from atlas.db.connection import connect
from atlas.db.migrate import assert_schema_current

log = logging.getLogger(__name__)


def move_document(
    catalog_root: Path,
    source: Path | str,
    destination: Path | str,
) -> dict:
    """
    Verschiebt ein PDF und aktualisiert die Datenbank.

    source kann sein:
      - absoluter oder relativer Pfad zum PDF
      - document_id (40-Zeichen SHA-256 Hex)

    destination kann sein:
      - neuer Pfad (absolut oder relativ zum cwd)
      - Verzeichnis (PDF-Name bleibt gleich)

    Returns:
        {"document_id": str, "old_path": str, "new_path": str}

    Raises:
        FileNotFoundError  wenn source-PDF nicht existiert
        FileExistsError    wenn destination bereits existiert
        ValueError         wenn document nicht in DB gefunden
    """
    db_path = catalog_root / ".atlas" / "catalog.db"
    conn    = connect(db_path)
    assert_schema_current(conn)

    # Source auflösen — Pfad oder document_id
    source = Path(source) if not isinstance(source, Path) else source
    dest   = Path(destination) if not isinstance(destination, Path) else destination

    if len(str(source)) == 64 and all(c in "0123456789abcdef" for c in str(source)):
        # document_id übergeben
        row = conn.execute(
            "SELECT document_id, file_path FROM documents WHERE document_id = ?",
            (str(source),),
        ).fetchone()
        if not row:
            raise ValueError(f"Dokument nicht gefunden: {source}")
        doc_id   = row["document_id"]
        src_path = Path(row["file_path"])
    else:
        src_path = source.resolve()
        row = conn.execute(
            "SELECT document_id FROM documents WHERE file_path = ?",
            (str(src_path),),
        ).fetchone()
        if not row:
            raise ValueError(f"Dokument nicht in DB: {src_path}")
        doc_id = row["document_id"]

    if not src_path.exists():
        raise FileNotFoundError(f"PDF nicht gefunden: {src_path}")

    # Destination auflösen
    dest = dest.resolve()
    if dest.is_dir():
        dest = dest / src_path.name
    if dest.exists():
        raise FileExistsError(f"Ziel existiert bereits: {dest}")

    # Zielverzeichnis anlegen
    dest.parent.mkdir(parents=True, exist_ok=True)

    # PDF verschieben
    shutil.move(str(src_path), str(dest))
    log.info("Moved: %s → %s", src_path.name, dest)

    # DB aktualisieren
    conn.execute(
        "UPDATE documents SET file_path=?, file_name=?, updated_at=datetime('now') "
        "WHERE document_id=?",
        (str(dest), dest.name, doc_id),
    )
    conn.commit()
    conn.close()

    return {
        "document_id": doc_id,
        "old_path":    str(src_path),
        "new_path":    str(dest),
    }
