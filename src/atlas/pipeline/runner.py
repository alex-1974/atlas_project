# src/atlas/pipeline/runner.py
"""Orchestrates the full ingestion pipeline for one document.

Steps:
  1. extract_text       — full text via PyMuPDF (+ pdftotext fallback)
  2. extract_metadata   — PDF metadata fields
  3. extract_layout     — layout lines + spans for DU
  4. extract_identifiers — DOI, ISBN, arXiv, PMID
  5. normalize_identifiers — canonicalise identifier values
  6. du                  — Document Understanding (all 15 sub-steps)
  7. detect_language     — primary + secondary language
  8. promote_du_metadata — copy title/authors from DU if metadata is empty
  9. promote_identifiers — copy best identifier into documents table
  10. knowledge_graph    — write local RDF triples to Oxigraph
  11. embeddings         — index semantic chunks in LanceDB
  12. update_fts         — refresh FTS5 index

Each step is idempotent. On failure the document's pipeline_status
is set to 'failed' with an error message, and the exception is
re-raised so the caller can decide whether to continue or abort.
"""
from __future__ import annotations

import json
import re
import sqlite3
import traceback
from pathlib import Path


# ── Status helpers ────────────────────────────────────────────────────────────

def _set_status(conn: sqlite3.Connection, document_id: str,
                status: str, error: str | None = None) -> None:
    conn.execute(
        """
        UPDATE documents
        SET pipeline_status = ?,
            pipeline_error  = ?,
            updated_at      = datetime('now')
        WHERE document_id = ?
        """,
        (status, error, document_id),
    )
    conn.commit()


# ── Extraction wrappers ───────────────────────────────────────────────────────

def _run_extract_text(catalog_root: Path, document_id: str, pdf_path: str) -> None:
    """Extract text via PyMuPDF with pdftotext fallback."""
    from atlas.db.connection import set_catalog_path
    set_catalog_path(catalog_root)
    from atlas.extract.text_pymupdf import extract_text_pymupdf
    extract_text_pymupdf(Path(pdf_path), document_id, force=False)


def _run_extract_metadata(catalog_root: Path, document_id: str, pdf_path: str) -> None:
    from atlas.db.connection import set_catalog_path
    set_catalog_path(catalog_root)
    from atlas.extract.pdf_metadata import extract_pdf_metadata
    extract_pdf_metadata()


def _run_extract_identifiers(catalog_root: Path, document_id: str) -> None:
    from atlas.db.connection import set_catalog_path
    set_catalog_path(catalog_root)
    from atlas.extract.identifiers import extract_identifiers
    extract_identifiers()


def _run_normalize_identifiers(catalog_root: Path) -> None:
    from atlas.db.connection import set_catalog_path
    set_catalog_path(catalog_root)
    from atlas.normalize.identifiers import normalize_identifiers
    normalize_identifiers()


def _run_extract_layout(conn: sqlite3.Connection,
                        document_id: str, pdf_path: str) -> None:
    from atlas.pipeline.extract.layout import run_extract_layout
    run_extract_layout(conn, document_id, pdf_path)


# ── Post-DU helpers ───────────────────────────────────────────────────────────

def _is_corrupt(text: str | None) -> bool:
    """True if a metadata string looks garbled or non-human."""
    if not text:
        return False
    if len(text) < 2:
        return False
    printable = sum(1 for c in text if c.isprintable())
    if printable / len(text) < 0.70:
        return True
    if re.search(r'\bmitech\b|\bcnx\b|,\s*,', text, re.IGNORECASE):
        return True
    if re.search(r'[A-Z]\.\d+\s+\w.*\d,\d', text):
        return True
    return False


def _promote_du_metadata(conn: sqlite3.Connection, document_id: str) -> None:
    """Copy title/authors from DU results when PDF metadata is empty."""
    row = conn.execute(
        "SELECT title, authors FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not row:
        return

    current_title   = row["title"]
    current_authors = row["authors"]

    # Title from DU
    if not current_title or _is_corrupt(current_title):
        # Schmutztitel detection: if page 0 has no body text, it is a
        # cover/series title page. Skip page 0 title blocks and start
        # the title search from page 1.
        p0_body = conn.execute(
            """
            SELECT AVG(s.body_like) AS avg_body, COUNT(*) AS block_count
            FROM du_blocks b
            JOIN du_block_signals s ON s.block_id = b.block_id
            WHERE b.document_id = ? AND b.page_index = 0
            """,
            (document_id,),
        ).fetchone()
        has_schmutztitel = (
            p0_body is not None
            and (p0_body["avg_body"] or 0.0) < 0.15
            and (p0_body["block_count"] or 0) <= 6
        )
        title_page_filter = "AND b.page_index >= 1" if has_schmutztitel else ""

        title_rows = conn.execute(
            f"""
            SELECT b.text, b.block_index, b.page_index
            FROM du_block_roles r
            JOIN du_blocks b ON b.block_id = r.block_id
            WHERE b.document_id = ? AND r.role = 'title'
            {title_page_filter}
            ORDER BY b.block_index
            LIMIT 6
            """,
            (document_id,),
        ).fetchall()

        title_parts = []
        last_title_idx = None
        subtitle = None
        subtitle_accepted = False

        for row_b in title_rows:
            text = (row_b["text"] or "").strip().replace("\n", " ")
            text = " ".join(text.split())
            idx  = row_b["block_index"]
            role_check = conn.execute(
                "SELECT role FROM du_block_roles r "
                "JOIN du_blocks b ON b.block_id = r.block_id "
                "WHERE b.document_id = ? AND b.block_index = ?",
                (document_id, idx),
            ).fetchone()
            role = role_check["role"] if role_check else "body"

            if not text or _is_corrupt(text):
                continue

            if role == "title":
                if last_title_idx is None or idx <= last_title_idx + 2:
                    title_parts.append(text)
                    last_title_idx = idx
                else:
                    break
            elif last_title_idx is not None and not subtitle_accepted:
                if (idx <= last_title_idx + 2
                        and role == "heading"
                        and len(text.split()) <= 8
                        and not text.endswith(".")):
                    subtitle = text
                    subtitle_accepted = True
                elif (idx <= last_title_idx + 2
                        and role == "body"
                        and len(text.split()) <= 5
                        and not text.endswith(".")):
                    title_parts.append(text)
                    last_title_idx = idx
                else:
                    break
            elif last_title_idx is None:
                continue

        if title_parts:
            title = " ".join(title_parts)
            if subtitle:
                title = f"{title}: {subtitle}"
            conn.execute(
                "UPDATE documents SET title = ? WHERE document_id = ?",
                (title, document_id),
            )

    # Authors from DU
    authors_empty = True
    if current_authors:
        try:
            parsed = json.loads(current_authors)
            if isinstance(parsed, list) and parsed:
                if all(not _is_corrupt(a) for a in parsed):
                    authors_empty = False
        except (json.JSONDecodeError, TypeError):
            pass

    if authors_empty:
        author_rows = conn.execute(
            """
            SELECT b.text, b.page_index, b.block_index
            FROM du_block_roles r
            JOIN du_blocks b ON b.block_id = r.block_id
            WHERE b.document_id = ? AND r.role = 'author'
              AND b.page_index <= 2
            ORDER BY b.block_index
            LIMIT 5
            """,
            (document_id,),
        ).fetchall()

        if not author_rows:
            author_rows = list(reversed(conn.execute(
                """
                SELECT b.text, b.page_index, b.block_index
                FROM du_block_roles r
                JOIN du_blocks b ON b.block_id = r.block_id
                WHERE b.document_id = ? AND r.role = 'author'
                ORDER BY b.block_index DESC
                LIMIT 5
                """,
                (document_id,),
            ).fetchall()))

        if author_rows:
            from atlas.understanding.core.text_patterns import normalize_letter_spaced
            authors = []
            for row_a in author_rows:
                text = " ".join(normalize_letter_spaced(row_a["text"] or "").split())
                if not text or _is_corrupt(text):
                    continue
                words = text.split()
                if len(words) < 2 or len(words) > 12:
                    continue
                lower = text.lower()
                bad_markers = (
                    "fig.", "figure", "table", "©", "http", "www",
                    "vol.", "isbn", "doi", "equation", "section",
                    "chapter", "appendix", "note", "references",
                    "b.1", "b.2", "b.3",
                    "temple", "church", "institute", "baptist",
                )
                if any(m in lower for m in bad_markers):
                    continue
                if re.search(r'\d+,\s*\d+', text):
                    continue
                if sum(1 for c in text if c.isdigit()) / max(len(text), 1) > 0.15:
                    continue
                authors.append(text)
            if authors:
                conn.execute(
                    "UPDATE documents SET authors = ? WHERE document_id = ?",
                    (json.dumps(authors, ensure_ascii=False), document_id),
                )

    conn.commit()


def _promote_identifiers(conn: sqlite3.Connection, document_id: str) -> None:
    """Copy best identifier values into the documents table."""
    for typ, col in [("doi", "doi"), ("arxiv_id", "arxiv_id"),
                     ("isbn", "isbn"), ("pmid", "pmid")]:
        row = conn.execute(
            """
            SELECT identifier_value FROM document_identifiers
            WHERE document_id = ? AND identifier_type = ?
            ORDER BY rowid LIMIT 1
            """,
            (document_id, typ),
        ).fetchone()
        if row:
            conn.execute(
                f"UPDATE documents SET {col} = COALESCE({col}, ?) "
                "WHERE document_id = ?",
                (row["identifier_value"], document_id),
            )
    conn.commit()


def _update_fts(conn: sqlite3.Connection, document_id: str) -> None:
    """Refresh the FTS5 index for this document."""
    row = conn.execute(
        "SELECT title, abstract FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    text_row = conn.execute(
        "SELECT text FROM extracted_texts WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    conn.execute(
        "DELETE FROM documents_fts WHERE document_id = ?", (document_id,)
    )
    conn.execute(
        "INSERT INTO documents_fts(document_id, title, abstract, body_text) "
        "VALUES (?, ?, ?, ?)",
        (
            document_id,
            row["title"]    if row else None,
            row["abstract"] if row else None,
            text_row["text"][:50_000] if text_row else None,
        ),
    )
    conn.commit()


def _populate_knowledge_graph(
    conn: sqlite3.Connection,
    document_id: str,
    catalog_root: Path | None,
) -> None:
    """Write initial triples for this document to the knowledge graph."""
    if catalog_root is None:
        return
    try:
        from atlas.knowledge.store import KnowledgeStore
        from atlas.knowledge.triples import write_document_to_store
        store = KnowledgeStore.open(catalog_root)
        n = write_document_to_store(conn, store, document_id)
        if n:
            import logging
            logging.getLogger(__name__).debug(
                "Knowledge graph: %d triples for %s", n, document_id[:12]
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Knowledge graph population failed for %s: %s", document_id[:12], exc
        )


def _index_embeddings(
    conn: sqlite3.Connection,
    document_id: str,
    catalog_root: Path | None,
) -> None:
    """Extract semantic chunks and write them to LanceDB."""
    if catalog_root is None:
        return
    try:
        from atlas.embeddings.store import EmbeddingStore
        from atlas.embeddings.index import index_document
        store = EmbeddingStore.open(catalog_root)
        n = index_document(conn, store, document_id)
        if n:
            import logging
            logging.getLogger(__name__).debug(
                "Embeddings: %d chunks for %s", n, document_id[:12]
            )
    except ImportError:
        pass
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Embedding indexing failed for %s: %s", document_id[:12], exc
        )


# ── Public API ────────────────────────────────────────────────────────────────

def run_pipeline(
    conn: sqlite3.Connection,
    document_id: str,
    pdf_path: str,
    catalog_root: Path | None = None,
) -> None:
    """Run the full ingestion pipeline for one document."""
    try:
        # Set catalog path for old-style modules that use get_connection()
        if catalog_root is not None:
            from atlas.db.connection import set_catalog_path
            set_catalog_path(catalog_root)

        # ── Pass 0: Pre-classification ────────────────────────────────────
        # Runs before any DU step. Determines book_score / structure_score
        # and boost signals. The profile is passed to run_du_pipeline() so
        # the Aggregate layer can apply quadrant-specific weights.
        from atlas.pipeline.profiling import profile_document
        profile = profile_document(Path(pdf_path))

        _set_status(conn, document_id, "extracting")
        _run_extract_text(catalog_root, document_id, pdf_path)
        _run_extract_metadata(catalog_root, document_id, pdf_path)
        _run_extract_layout(conn, document_id, pdf_path)
        _run_extract_identifiers(catalog_root, document_id)
        _run_normalize_identifiers(catalog_root)

        _set_status(conn, document_id, "du_processing")
        from atlas.understanding.pipeline import run_du_pipeline
        run_du_pipeline(conn, document_id, profile=profile)
        from atlas.pipeline.detect.language import run_detect_language
        run_detect_language(conn, document_id)

        _set_status(conn, document_id, "indexing")
        _promote_du_metadata(conn, document_id)
        _promote_identifiers(conn, document_id)
        _populate_knowledge_graph(conn, document_id, catalog_root)
        _index_embeddings(conn, document_id, catalog_root)
        _update_fts(conn, document_id)

        _set_status(conn, document_id, "indexed")

    except Exception as exc:
        _set_status(conn, document_id, "failed",
                    error=f"{type(exc).__name__}: {exc}\n"
                          f"{traceback.format_exc()[-800:]}")
        raise
