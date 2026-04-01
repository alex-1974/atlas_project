# src/atlas/pipeline/runner.py
"""Orchestrates the full ingestion pipeline for one document.

Steps:
  1. extract_text       — full text via PyMuPDF (+ pdftotext fallback)
  2. extract_metadata   — PDF metadata fields
  3. extract_layout     — layout lines + spans for DU
  4. extract_identifiers — DOI, ISBN, arXiv, PMID
  5. normalize_identifiers — canonicalise identifier values
  6. du                  — Document Understanding (all 15 sub-steps)
  7. promote_du_metadata — copy title/authors from DU if metadata is empty
  8. promote_identifiers — copy best identifier into documents table
  9. update_fts          — refresh FTS5 index

Each step is idempotent. On failure the document's pipeline_status
is set to 'failed' with an error message, and the exception is
re-raised so the caller can decide whether to continue or abort.
"""
from __future__ import annotations

import json
import sqlite3
import traceback
from pathlib import Path

from atlas.pipeline.extract.text import run_extract_text
from atlas.pipeline.extract.metadata import run_extract_metadata
from atlas.pipeline.extract.layout import run_extract_layout
from atlas.pipeline.extract.identifiers import run_extract_identifiers
from atlas.pipeline.normalize.identifiers import run_normalize_identifiers
from atlas.understanding.pipeline import run_du_pipeline
from atlas.pipeline.detect.language import run_detect_language


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


# ── Post-DU helpers ───────────────────────────────────────────────────────────

def _is_corrupt(text: str | None) -> bool:
    """True if a metadata string looks like a garbled or non-human value.

    Catches:
    - High ratio of non-printable / non-ASCII characters (encoding mojibake)
    - Scanner software artefacts: 'mitech-bur013, ,CNX74412JT'
    - Index entries: 'B.2.3 Standard Wood Screws1,5'
    - Index entries with page numbers: 'Zion Baptist Temple, 476, 478'
    - Caption fragments: 'A, 47: Jen Deadman'
    """
    if not text:
        return True
    t = text.strip()
    if not t:
        return True

    # High ratio of non-printable / non-ASCII
    printable_ascii = sum(1 for c in t if 32 <= ord(c) < 127)
    if printable_ascii / max(len(t), 1) < 0.70:
        return True

    # No alphabetic content at all
    alpha = sum(1 for c in t if c.isalpha())
    if alpha == 0:
        return True

    # High digit ratio — index entries, table data, page-number lists
    digit_ratio = sum(1 for c in t if c.isdigit()) / max(len(t), 1)
    if digit_ratio > 0.15:
        return True

    # Scanner artefact: comma-separated code strings (alphanumeric, no spaces)
    # e.g. "mitech-bur013, ,CNX74412JT"
    import re as _re
    tokens = [tok.strip() for tok in t.split(',') if tok.strip()]
    code_tokens = sum(
        1 for tok in tokens
        if _re.search(r'[A-Za-z]\d|\d[A-Za-z]', tok) and ' ' not in tok
    )
    if code_tokens >= 2:
        return True

    # Index entry starting with section number: "B.2.3 ..." or "11.3.1 ..."
    if _re.match(r'^[A-Z]\.\d|^\d+\.\d+\.\d+', t):
        return True

    # Caption fragment: single letter + comma + number: "A, 47: ..."
    if _re.match(r'^[A-Z],\s*\d+', t):
        return True

    return False


def _promote_du_metadata(conn: sqlite3.Connection, document_id: str) -> None:
    """Fill in title and authors from DU pipeline if metadata fields are empty.

    After DU, du_block_roles contains blocks with role='title' and
    role='author'. These are used as fallback when PDF metadata extraction
    produced empty or corrupt values.

    Title: the first block with role='title' by block_index.
    Authors: all blocks with role='author', joined as a JSON array.
    """
    doc = conn.execute(
        "SELECT title, authors FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not doc:
        return

    current_title   = doc["title"]
    current_authors = doc["authors"]

    # ── Title ─────────────────────────────────────────────────────────────────
    if not current_title or _is_corrupt(current_title):
        near_start = conn.execute(
            """
            SELECT b.block_index, b.text, r.role
            FROM du_block_roles r
            JOIN du_blocks b ON b.block_id = r.block_id
            WHERE b.document_id = ?
              AND b.block_index <= 10
            ORDER BY b.block_index
            """,
            (document_id,),
        ).fetchall()

        if near_start:
            from atlas.understanding.core.text_patterns import normalize_letter_spaced
            title_parts: list[str] = []
            subtitle: str | None = None
            last_title_idx: int | None = None
            subtitle_accepted = False

            for row in near_start:
                idx  = row["block_index"]
                role = row["role"]
                text = " ".join(normalize_letter_spaced(row["text"] or "").split())
                if not text:
                    continue

                if role == "title":
                    # Only merge consecutive title blocks (gap ≤ 2)
                    if last_title_idx is None or idx <= last_title_idx + 2:
                        title_parts.append(text)
                        last_title_idx = idx
                    else:
                        break  # non-consecutive title block — stop
                elif last_title_idx is not None and not subtitle_accepted:
                    # Accept exactly one short heading immediately after titles
                    # as a subtitle — e.g. "A Guide to Good Practice"
                    if (idx <= last_title_idx + 2
                            and role == "heading"
                            and len(text.split()) <= 8
                            and not text.endswith(".")):
                        subtitle = text
                        subtitle_accepted = True
                    # Also accept a short body block immediately after title
                    # as title continuation — e.g. "EAST SUFFOLK" after
                    # "MEDIEVAL TIMBER FRAMED HOUSES IN" (OCR split title)
                    elif (idx <= last_title_idx + 2
                            and role == "body"
                            and len(text.split()) <= 5
                            and not text.endswith(".")):
                        title_parts.append(text)
                        last_title_idx = idx
                    else:
                        break  # stop after first non-title block
                elif last_title_idx is None:
                    continue  # haven't seen a title yet

            if title_parts:
                title = " ".join(title_parts)
                if subtitle:
                    title = f"{title}: {subtitle}"
                conn.execute(
                    "UPDATE documents SET title = ? WHERE document_id = ?",
                    (title, document_id),
                )

    # ── Authors ───────────────────────────────────────────────────────────────
    authors_empty = True
    if current_authors:
        try:
            parsed = json.loads(current_authors)
            if isinstance(parsed, list) and parsed:
                # All entries must pass the corruption check
                if all(not _is_corrupt(a) for a in parsed):
                    authors_empty = False
        except (json.JSONDecodeError, TypeError):
            pass

    if authors_empty:
        # First: look for author blocks on first 2 pages
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

        # Fallback: look for author blocks near the end of the document
        # (e.g. "Über den Autor" box at end of journal articles)
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
            for row in author_rows:
                text = " ".join(normalize_letter_spaced(row["text"] or "").split())
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
                    # Timber-Manual-style entries
                    "b.1", "b.2", "b.3",  # appendix section refs
                    "temple", "church", "institute", "baptist",
                )
                if any(m in lower for m in bad_markers):
                    continue
                # Reject strings that look like index entries (contain digits
                # mixed with text followed by comma+numbers: "Screws1,5")
                import re as _re
                if _re.search(r'\d+,\s*\d+', text):
                    continue
                # Reject if more than 30% digits (table data, not names)
                digit_ratio = sum(1 for c in text if c.isdigit()) / max(len(text), 1)
                if digit_ratio > 0.15:
                    continue
                authors.append(text)
            if authors:
                conn.execute(
                    "UPDATE documents SET authors = ? WHERE document_id = ?",
                    (json.dumps(authors, ensure_ascii=False), document_id),
                )

    conn.commit()


def _promote_identifiers(conn: sqlite3.Connection, document_id: str) -> None:
    """Copy the best identifier values into the documents table."""
    for typ, col in [("doi", "doi"), ("arxiv_id", "arxiv_id"),
                     ("isbn", "isbn"), ("pmid", "pmid")]:
        row = conn.execute(
            "SELECT identifier_value FROM document_identifiers "
            "WHERE document_id=? AND identifier_type=? LIMIT 1",
            (document_id, typ),
        ).fetchone()
        if row:
            conn.execute(
                f"UPDATE documents SET {col} = COALESCE({col}, ?) WHERE document_id = ?",
                (row["identifier_value"], document_id),
            )
    conn.commit()


def _update_fts(conn: sqlite3.Connection, document_id: str) -> None:
    """Refresh the FTS5 entry for this document."""
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
            row["title"] if row else None,
            row["abstract"] if row else None,
            text_row["text"][:50_000] if text_row else None,
        ),
    )
    conn.commit()


def _index_embeddings(
    conn: sqlite3.Connection,
    document_id: str,
    catalog_root: Path | None,
) -> None:
    """Extract semantic chunks and write them to LanceDB.

    Non-critical — if LanceDB or sentence-transformers are not installed,
    this step is silently skipped. atlas similar will not work until
    embeddings are indexed, but the rest of the pipeline is unaffected.
    """
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
        # lancedb / sentence-transformers not installed — skip silently
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
    catalog_root: "Path | None" = None,
) -> None:
    """Run the full ingestion pipeline for one document.

    catalog_root is needed for the knowledge graph store and embeddings.
    Updates pipeline_status throughout. Raises on failure.
    """
    try:
        _set_status(conn, document_id, "extracting")
        run_extract_text(conn, document_id, pdf_path)
        run_extract_metadata(conn, document_id, pdf_path)
        run_extract_layout(conn, document_id, pdf_path)
        run_extract_identifiers(conn, document_id, pdf_path)
        run_normalize_identifiers(conn, document_id)

        _set_status(conn, document_id, "du_processing")
        run_du_pipeline(conn, document_id)
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
                    error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}")
        raise
