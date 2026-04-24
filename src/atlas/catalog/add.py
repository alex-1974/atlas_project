# src/atlas/catalog/add.py
"""Document ingestion pipeline — atlas add.

add_document(root, pdf_path) is the single entry point.
It runs the full pipeline for one PDF and returns:
    {"document_id": str, "skipped": bool}

Internal sequence:
    1. Hash PDF → document_id (SHA-256)
    2. Check if already indexed → skip if yes
    3. Run base pipeline (extract → normalize → segment → DU)
    4. Populate knowledge graph (local triples)
    5. Index embeddings (LanceDB)
    6. Extract keywords (local, no network)
    7. Set pipeline_status = 'indexed'

External enrichment (Wikidata, CrossRef, RVK) is NOT run automatically —
it requires explicit `atlas enrich` to keep `atlas add` fast and offline.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from atlas.db.connection import connect
from atlas.db.migrate import assert_schema_current
from atlas.pipeline.runner import run_pipeline

log = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def add_document(
    catalog_root: Path,
    pdf_path: Path,
) -> dict:
    """Index one PDF document.

    Returns:
        {"document_id": str, "skipped": bool}

    Raises on unrecoverable errors (corrupt PDF, missing file, etc.).
    """
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF nicht gefunden: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Kein PDF: {pdf_path}")

    document_id = _hash_file(pdf_path)

    db_path = catalog_root / ".atlas" / "catalog.db"
    conn    = connect(db_path)
    assert_schema_current(conn)

    # Already fully indexed?
    row = conn.execute(
        "SELECT pipeline_status FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    if row and row["pipeline_status"] == "indexed":
        conn.close()
        return {"document_id": document_id, "skipped": True}

    # Register document if not yet known
    if not row:
        conn.execute(
            """
            INSERT INTO documents (document_id, file_path, file_name, file_size,
                                   pipeline_status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                document_id,
                str(pdf_path),
                pdf_path.name,
                pdf_path.stat().st_size,
            ),
        )
        conn.commit()

    try:
        # Base pipeline (extract → DU) + knowledge graph + embeddings
        run_pipeline(conn, document_id, str(pdf_path),
                     catalog_root=catalog_root)

        # Local keyword extraction (fast, no network)
        _run_keywords(conn, document_id, catalog_root)

        conn.execute(
            "UPDATE documents SET pipeline_status = 'indexed' WHERE document_id = ?",
            (document_id,),
        )
        conn.commit()

    except Exception as exc:
        log.exception("Pipeline failed for %s: %s", pdf_path.name, exc)
        conn.execute(
            "UPDATE documents SET pipeline_status = 'failed', pipeline_error = ? "
            "WHERE document_id = ?",
            (str(exc)[:500], document_id),
        )
        conn.commit()
        conn.close()
        raise

    conn.close()
    return {"document_id": document_id, "skipped": False}


def add_directory(
    catalog_root: Path,
    directory: Path,
    resume: bool = False,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict:
    """Index all PDFs in a directory.

    Args:
        include: Glob-Muster die eingeschlossen werden (z.B. ["**/*.pdf"])
        exclude: Glob-Muster die ausgeschlossen werden (z.B. ["drafts/", "*_temp*"])

    Returns:
        {"ok": int, "skipped": int, "failed": int,
         "errors": list[tuple[str, str]]}
    """
    import fnmatch
    pdfs = sorted(directory.rglob("*.pdf"))

    # Include-Filter: wenn angegeben, nur passende Pfade
    if include:
        pdfs = [
            p for p in pdfs
            if any(fnmatch.fnmatch(str(p.relative_to(directory)), pat)
                   for pat in include)
            or any(fnmatch.fnmatch(p.name, pat) for pat in include)
        ]

    # Exclude-Filter: Pfade die einem Muster entsprechen ausschließen
    if exclude:
        def _excluded(p: Path) -> bool:
            rel = str(p.relative_to(directory))
            return any(
                fnmatch.fnmatch(rel, pat)
                or fnmatch.fnmatch(p.name, pat)
                or any(pat.rstrip("/") in part for part in p.parts)
                for pat in exclude
            )
        pdfs = [p for p in pdfs if not _excluded(p)]
    ok = skipped = failed = 0
    errors: list[tuple[str, str]] = []

    for pdf in pdfs:
        try:
            result = add_document(catalog_root, pdf)
            if result["skipped"]:
                skipped += 1
            else:
                ok += 1
                log.info("Indexed: %s", pdf.name)
        except Exception as exc:
            failed += 1
            errors.append((pdf.name, str(exc)))
            log.error("Failed: %s — %s", pdf.name, exc)

    return {"ok": ok, "skipped": skipped, "failed": failed, "errors": errors}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_file(path: Path) -> str:
    """SHA-256 of file content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_keywords(
    conn,
    document_id: str,
    catalog_root: Path,
) -> None:
    """Extract keywords locally and write to knowledge graph."""
    try:
        from atlas.enrich.keywords import extract_keywords
        from atlas.knowledge.store import KnowledgeStore
        store = KnowledgeStore.open(catalog_root)
        extract_keywords(conn, document_id, store=store)
    except Exception as exc:
        # Keywords are non-critical — log and continue
        log.debug("Keyword extraction failed for %s: %s", document_id[:12], exc)
