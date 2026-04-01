# src/atlas/catalog/remove.py
"""Document removal — atlas remove.

remove_document(root, document_id) removes a document cleanly from:
  1. SQLite  — documents table + all DU tables (CASCADE)
  2. Oxigraph — named graph for this document
  3. LanceDB  — all embedding chunks for this document
  4. FTS5     — full-text index entry

Returns True on success, False if the document was not found.
"""
from __future__ import annotations

import logging
from pathlib import Path

from atlas.db.connection import connect
from atlas.db.migrate import assert_schema_current

log = logging.getLogger(__name__)


def remove_document(
    catalog_root: Path,
    document_id: str,
) -> bool:
    """Remove one document from all index layers.

    Returns True on success, False if not found.
    """
    db_path = catalog_root / ".atlas" / "catalog.db"
    conn    = connect(db_path)
    assert_schema_current(conn)

    row = conn.execute(
        "SELECT file_name FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    if not row:
        conn.close()
        return False

    file_name = row["file_name"]

    # ── 1. FTS5 ───────────────────────────────────────────────────────────────
    try:
        conn.execute(
            "DELETE FROM documents_fts WHERE document_id = ?",
            (document_id,),
        )
    except Exception as exc:
        log.debug("FTS delete skipped for %s: %s", document_id[:12], exc)

    # ── 2. SQLite — DU tables (CASCADE handles child rows) ────────────────────
    conn.execute(
        "DELETE FROM documents WHERE document_id = ?",
        (document_id,),
    )
    conn.commit()
    conn.close()

    # ── 3. Oxigraph knowledge graph ───────────────────────────────────────────
    try:
        from atlas.knowledge.store import KnowledgeStore
        store = KnowledgeStore.open(catalog_root)
        store.remove_document(document_id)
        log.debug("Knowledge graph: removed %s", document_id[:12])
    except Exception as exc:
        log.warning("Knowledge graph removal failed for %s: %s",
                    document_id[:12], exc)

    # ── 4. LanceDB embeddings ─────────────────────────────────────────────────
    try:
        from atlas.embeddings.store import EmbeddingStore
        emb_store = EmbeddingStore.open(catalog_root)
        emb_store.remove_document(document_id)
        log.debug("Embeddings: removed %s", document_id[:12])
    except Exception as exc:
        log.debug("Embedding removal skipped for %s: %s",
                  document_id[:12], exc)

    log.info("Removed: %s (%s)", file_name, document_id[:12])
    return True
