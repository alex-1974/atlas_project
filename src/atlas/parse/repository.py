"""
atlas.parse.repository

Persistiert ParsedDocument-Ergebnisse in SQLite.

Schreibt:
  - documents:      Metadaten (title, authors, year, doi, isbn, du_document_type, ...)
  - du_documents:   Dokumentkontext (is_scan, source_kind)
  - du_section_tree: Section-Tree

Liest/schreibt nichts zu den alten DU-Schicht-Tabellen (du_blocks,
du_block_geometry etc.) — diese werden von atlas.understanding befüllt
bis die Migration abgeschlossen ist.

Idempotent: mehrfaches Aufrufen mit demselben document_id ist sicher.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .logging import get_logger
from .pipeline import ParsedDocument

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def save_parse_result(
    conn: sqlite3.Connection,
    document_id: str,
    doc: ParsedDocument,
) -> None:
    """
    Schreibt ParsedDocument in SQLite.

    Überschreibt bestehende Metadaten nur wenn pipeline_ok=True.
    Bei pipeline_ok=False wird nur pipeline_status='failed' und
    pipeline_error gesetzt.
    """
    if not doc.pipeline_ok:
        conn.execute(
            """
            UPDATE documents
            SET pipeline_status = 'failed',
                pipeline_error  = ?,
                updated_at      = datetime('now')
            WHERE document_id = ?
            """,
            (doc.error, document_id),
        )
        conn.commit()
        logger.warning("save_parse_result: pipeline failed for %s — %s",
                       document_id[:12], doc.error)
        return

    # ── documents ────────────────────────────────────────────────────────
    meta = doc.metadata
    authors_json = json.dumps(meta.authors if meta else [], ensure_ascii=False)

    conn.execute(
        """
        UPDATE documents SET
            title               = COALESCE(?, title),
            authors             = COALESCE(?, authors),
            year                = COALESCE(?, year),
            doi                 = COALESCE(?, doi),
            isbn                = COALESCE(?, isbn),
            du_document_type    = ?,
            metadata_confidence = ?,
            has_native_text     = ?,
            pipeline_status     = 'du_done',
            pipeline_error      = NULL,
            updated_at          = datetime('now')
        WHERE document_id = ?
        """,
        (
            meta.title         if meta and meta.title else None,
            authors_json       if meta and meta.authors else None,
            meta.year          if meta and meta.year else None,
            meta.doi           if meta and meta.doi else None,
            meta.isbn          if meta and meta.isbn else None,
            doc.doc_class,
            meta.title_confidence if meta else 0.0,
            0 if doc.is_scan else 1,
            document_id,
        ),
    )

    # ISSN in document_identifiers (falls Tabelle vorhanden)
    if meta and meta.issn:
        try:
            conn.execute(
                """
                INSERT INTO document_identifiers (document_id, identifier_type, identifier_value)
                VALUES (?, 'issn', ?)
                ON CONFLICT (document_id, identifier_type, identifier_value) DO NOTHING
                """,
                (document_id, meta.issn),
            )
        except sqlite3.OperationalError:
            pass  # Tabelle existiert möglicherweise noch nicht

    # ── du_documents ──────────────────────────────────────────────────────
    source_kind  = "image_pdf" if doc.is_scan else "born_digital_pdf"
    text_source  = "ocr"       if doc.is_scan else "pdf_native"

    conn.execute(
        """
        INSERT INTO du_documents (
            document_id, source_kind, text_source,
            geometry_source, has_native_text, has_reliable_geometry,
            created_at
        ) VALUES (?, ?, ?, 'pymupdf', ?, 1, datetime('now'))
        ON CONFLICT (document_id) DO UPDATE SET
            source_kind        = excluded.source_kind,
            text_source        = excluded.text_source,
            has_native_text    = excluded.has_native_text
        """,
        (document_id, source_kind, text_source, 0 if doc.is_scan else 1),
    )

    # ── du_section_tree ───────────────────────────────────────────────────
    conn.execute(
        "DELETE FROM du_section_tree WHERE document_id = ?",
        (document_id,),
    )

    if doc.sections:
        # Stack für parent_section_node_id Berechnung
        # Wir müssen die node_ids kennen — SQLite AUTOINCREMENT gibt sie zurück
        # Strategie: alle Zeilen erst sammeln, dann mit expliziten IDs einfügen

        # Maximale vorhandene node_id ermitteln
        max_id_row = conn.execute(
            "SELECT COALESCE(MAX(section_node_id), 0) FROM du_section_tree"
        ).fetchone()
        next_id = (max_id_row[0] or 0) + 1

        rows: list[tuple] = []
        # Stack: [(level, node_id)]
        stack: list[tuple[int, int]] = []

        for sec in doc.sections:
            node_id = next_id
            next_id += 1

            # Parent aus Stack
            while stack and stack[-1][0] >= sec.level:
                stack.pop()
            parent_id = stack[-1][1] if stack else None

            rows.append((
                node_id,
                document_id,
                parent_id,
                None,                    # heading_block_id — nicht verfügbar
                sec.block_start,
                sec.block_end,
                sec.page_start,
                sec.page_end,
                sec.level,
                sec.title,
                sec.title.lower() if sec.title else None,
                f"parse.v1:{sec.source}",
            ))

            if sec.level <= (stack[-1][0] if stack else 999):
                stack.append((sec.level, node_id))
            else:
                stack.append((sec.level, node_id))

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.executemany(
                """
                INSERT INTO du_section_tree (
                    section_node_id, document_id, parent_section_node_id,
                    heading_block_id, start_block_index, end_block_index,
                    page_start, page_end, level, title, title_normalized, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    conn.commit()

    logger.info(
        "save_parse_result: %s — type=%s title=%r sections=%d",
        document_id[:12],
        doc.doc_class,
        (meta.title[:40] if meta and meta.title else None),
        len(doc.sections),
    )
