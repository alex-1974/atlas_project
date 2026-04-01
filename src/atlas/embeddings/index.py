# src/atlas/embeddings/index.py
"""Populate the LanceDB embedding store from DU pipeline results.

Extracts semantic chunks from du_blocks (body paragraphs, abstracts,
section headings) and writes them to the vector store.

Chunking strategy:
  - Abstract: the full abstract text as one chunk
  - Section headings: heading text + first 300 chars of following body
  - Dense body paragraphs: blocks with ≥ 40 words, not already covered
    by a heading chunk
  - Skip: page_furniture, noise, caption, reference blocks
"""
from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_MIN_BODY_WORDS = 40   # minimum words for a standalone body chunk
_HEADING_CONTEXT_CHARS = 300   # characters of body text appended to heading


# ── Public API ────────────────────────────────────────────────────────────────

def index_document(
    conn: sqlite3.Connection,
    store,
    document_id: str,
) -> int:
    """Extract chunks from a document and write to the embedding store.

    Returns the number of chunks written.
    """
    chunks = _extract_chunks(conn, document_id)
    if not chunks:
        return 0
    return store.add_document(document_id, chunks)


def reindex_document(
    conn: sqlite3.Connection,
    store,
    document_id: str,
) -> int:
    """Remove existing vectors and re-index a document."""
    store.remove_document(document_id)
    return index_document(conn, store, document_id)


# ── Chunk extraction ──────────────────────────────────────────────────────────

def _extract_chunks(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[dict]:
    """Extract semantic chunks from DU results for one document."""
    # Load all blocks with roles
    blocks = conn.execute(
        """
        SELECT b.block_index, b.page_index, b.text, r.role
        FROM du_blocks b
        JOIN du_block_roles r ON r.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()

    if not blocks:
        return []

    # Index by block_index for fast lookup
    block_map = {row["block_index"]: dict(row) for row in blocks}
    max_idx   = max(block_map) if block_map else 0

    chunks: list[dict] = []
    covered: set[int] = set()   # block_indices already in a chunk

    # ── Abstract ──────────────────────────────────────────────────────────────
    abstract_text = _extract_abstract(conn, document_id)
    if abstract_text:
        # Find the abstract block index
        for row in blocks:
            if row["role"] in ("front_matter",) and "abstract" in (row["text"] or "").lower():
                abstract_idx = row["block_index"]
                break
        else:
            abstract_idx = 0
        chunks.append({
            "text":        abstract_text[:1500],
            "page":        block_map.get(abstract_idx, {}).get("page_index", 0),
            "block_index": abstract_idx,
        })
        covered.add(abstract_idx)

    # ── Section headings with context ────────────────────────────────────────
    for row in blocks:
        if row["role"] != "heading":
            continue
        idx       = row["block_index"]
        heading_t = (row["text"] or "").strip()
        if not heading_t or len(heading_t) < 3:
            continue

        # Collect following body text
        context_parts = [heading_t]
        context_chars = 0
        j = idx + 1
        while j <= min(idx + 20, max_idx) and context_chars < _HEADING_CONTEXT_CHARS:
            nb = block_map.get(j)
            if nb and nb["role"] == "body":
                t = (nb["text"] or "").strip()
                if t:
                    context_parts.append(t)
                    context_chars += len(t)
                    covered.add(j)
            j += 1

        covered.add(idx)
        chunks.append({
            "text":        " ".join(context_parts)[:1500],
            "page":        row["page_index"],
            "block_index": idx,
        })

    # ── Dense body paragraphs ─────────────────────────────────────────────────
    for row in blocks:
        if row["role"] != "body":
            continue
        idx = row["block_index"]
        if idx in covered:
            continue
        text = (row["text"] or "").strip()
        wc   = len(text.split())
        if wc < _MIN_BODY_WORDS:
            continue
        covered.add(idx)
        chunks.append({
            "text":        text[:1500],
            "page":        row["page_index"],
            "block_index": idx,
        })

    return chunks


def _extract_abstract(conn: sqlite3.Connection, document_id: str) -> str:
    """Try to extract the abstract text from the document."""
    # Check documents table first
    row = conn.execute(
        "SELECT abstract FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row and row["abstract"]:
        return row["abstract"].strip()

    # Fall back to blocks in abstract zone
    abstract_blocks = conn.execute(
        """
        SELECT b.text
        FROM du_block_zones z
        JOIN du_blocks b ON b.block_id = z.block_id
        JOIN du_block_roles r ON r.block_id = b.block_id
        WHERE b.document_id = ? AND z.zone = 'abstract' AND r.role = 'body'
        ORDER BY b.block_index
        LIMIT 10
        """,
        (document_id,),
    ).fetchall()

    if abstract_blocks:
        return " ".join(r["text"] for r in abstract_blocks if r["text"])[:1500]
    return ""
