# src/atlas/knowledge/triples.py
"""Generate RDF triples from local Atlas data (DU results + SQLite metadata).

This module bridges the SQLite world (Phase 1 output) and the RDF world
(Phase 2 Oxigraph store).  It produces the initial set of triples for
every document from data we already have — no external API calls.

External enrichment (Wikidata, ORCID, CrossRef) is handled separately
in `enrich/`.

Triple generation covers:
  - Document identity and type
  - Identifier assertions (DOI, ISBN, arXiv, PMID)
  - Authorship
  - Publication venue (journal from metadata)
  - Language
  - Section structure (via du_section_tree)
  - Citations (via du_block_roles reference blocks)
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from pyoxigraph import NamedNode, Literal

from atlas.knowledge.store import (
    KnowledgeStore, P, T,
    doc_uri, author_uri_from_name, journal_uri,
    _slugify,
)


# ── Document type mapping ─────────────────────────────────────────────────────

_TYPE_MAP: dict[str, NamedNode] = {
    "article":  T["Paper"],
    "monograph":T["Book"],
    "thesis":   T["Thesis"],
    "report":   T["Report"],
    "archival": T["Document"],
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_document_triples(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[tuple[NamedNode, NamedNode, NamedNode | Literal]]:
    """Return all triples for a document from local SQLite data.

    Reads from: documents, du_block_roles, du_blocks, du_section_tree.
    Does not access any external API.
    """
    row = conn.execute(
        """
        SELECT title, authors, year, doi, arxiv_id, isbn, pmid,
               journal, language, du_document_type
        FROM documents WHERE document_id = ?
        """,
        (document_id,),
    ).fetchone()

    if not row:
        return []

    triples: list[tuple[NamedNode, NamedNode, NamedNode | Literal]] = []
    doc = doc_uri(document_id)

    # ── Type ─────────────────────────────────────────────────────────────────
    doc_type = (row["du_document_type"] or "").lower()
    rdf_type = _TYPE_MAP.get(doc_type, T["Document"])
    triples.append((doc, P["type"], rdf_type))

    # ── Title ─────────────────────────────────────────────────────────────────
    if row["title"]:
        lang = row["language"] or None
        triples.append((doc, P["title"], KnowledgeStore.lit(row["title"], lang)))

    # ── Year ──────────────────────────────────────────────────────────────────
    if row["year"]:
        triples.append((doc, P["year"], KnowledgeStore.int_lit(int(row["year"]))))

    # ── Language ──────────────────────────────────────────────────────────────
    if row["language"]:
        triples.append((doc, P["language"], KnowledgeStore.lit(row["language"])))

    # ── Identifiers ───────────────────────────────────────────────────────────
    if row["doi"]:
        triples.append((doc, P["has_doi"], KnowledgeStore.lit(row["doi"])))
    if row["arxiv_id"]:
        triples.append((doc, P["has_arxiv_id"], KnowledgeStore.lit(row["arxiv_id"])))
    if row["isbn"]:
        triples.append((doc, P["has_isbn"], KnowledgeStore.lit(row["isbn"])))
    if row["pmid"]:
        triples.append((doc, P["has_pmid"], KnowledgeStore.lit(row["pmid"])))

    # ── Authors ───────────────────────────────────────────────────────────────
    triples.extend(_author_triples(doc, row["authors"]))

    # ── Journal ───────────────────────────────────────────────────────────────
    if row["journal"]:
        j_node = journal_uri(_slugify(row["journal"]))
        triples.append((doc, P["published_in"], j_node))
        triples.append((j_node, P["type"], T["Journal"]))
        triples.append((j_node, P["label"], KnowledgeStore.lit(row["journal"])))

    # ── Citation triples from reference blocks ────────────────────────────────
    triples.extend(_citation_triples(conn, document_id, doc))

    return triples


def write_document_to_store(
    conn: sqlite3.Connection,
    store: KnowledgeStore,
    document_id: str,
) -> int:
    """Build and write all triples for one document. Returns triple count."""
    triples = build_document_triples(conn, document_id)
    if triples:
        store.add_doc_triples(document_id, triples)
    return len(triples)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _author_triples(
    doc: NamedNode,
    authors_json: str | None,
) -> list[tuple[NamedNode, NamedNode, NamedNode | Literal]]:
    """Generate authored_by triples from the authors JSON array."""
    if not authors_json:
        return []
    try:
        authors = json.loads(authors_json)
        if not isinstance(authors, list):
            return []
    except (json.JSONDecodeError, TypeError):
        return []

    triples = []
    for name in authors:
        if not name or not isinstance(name, str):
            continue
        name = name.strip()
        if not name:
            continue
        author = author_uri_from_name(name)
        triples.append((doc,    P["authored_by"], author))
        triples.append((author, P["type"],        T["Author"]))
        triples.append((author, P["label"],       KnowledgeStore.lit(name)))
    return triples


def _citation_triples(
    conn: sqlite3.Connection,
    document_id: str,
    doc: NamedNode,
) -> list[tuple[NamedNode, NamedNode, NamedNode | Literal]]:
    """Extract cites-triples from reference blocks.

    For each reference block, try to extract a DOI or title that
    identifies the cited work.  If found, create an atlas:cites triple.
    If not, create a stub node with the raw reference text as label.
    """
    ref_blocks = conn.execute(
        """
        SELECT b.block_id, b.text
        FROM du_block_roles r
        JOIN du_blocks b ON b.block_id = r.block_id
        WHERE b.document_id = ? AND r.role = 'reference'
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()

    triples = []
    for i, row in enumerate(ref_blocks):
        text = (row["text"] or "").strip()
        if not text or len(text) < 10:
            continue

        # Try to extract a DOI from the reference text
        doi_match = re.search(
            r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', text, re.IGNORECASE
        )
        if doi_match:
            doi = doi_match.group(0).rstrip(".")
            # Use DOI URL as the cited work's URI
            cited = NamedNode("https://doi.org/" + doi)
            triples.append((doc, P["cites"], cited))
            triples.append((cited, P["has_doi"], KnowledgeStore.lit(doi)))
        else:
            # Stub node — identified only by document + position
            stub_id = f"{document_id[:12]}_ref_{i:04d}"
            cited = NamedNode("https://atlas.local/ref/" + stub_id)
            triples.append((doc, P["cites"], cited))
            # Store the raw text as label for future enrichment
            triples.append((
                cited, P["label"],
                KnowledgeStore.lit(text[:200])
            ))

    return triples
