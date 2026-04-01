# src/atlas/knowledge/store.py
"""Oxigraph RDF store — connection, namespaces, and low-level helpers.

One store per catalog, persisted at `.atlas/knowledge/`.
Each document occupies its own Named Graph:
    <https://atlas.local/doc/{document_id}>

This allows efficient per-document deletion (`atlas remove`) and
per-document SPARQL queries without scanning the full graph.

Pyoxigraph 0.5 API note
-----------------------
Version 0.5 requires `Quad` (subject, predicate, object, graph_name)
rather than `Triple`.  All helper functions here take care of this
transparently — callers work with (s, p, o) tuples.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from pyoxigraph import (
    Store,
    NamedNode,
    Literal,
    Quad,
    DefaultGraph,
)


# ── Namespace constants ───────────────────────────────────────────────────────

ATLAS   = "https://atlas.local/ontology#"
ATLAS_D = "https://atlas.local/doc/"
ATLAS_A = "https://atlas.local/author/"
ATLAS_J = "https://atlas.local/journal/"

OWL     = "http://www.w3.org/2002/07/owl#"
RDF     = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS    = "http://www.w3.org/2000/01/rdf-schema#"
XSD     = "http://www.w3.org/2001/XMLSchema#"

WD      = "https://www.wikidata.org/entity/"
ORCID   = "https://orcid.org/"
DOI_URL = "https://doi.org/"
GND_URL = "https://d-nb.info/gnd/"

# Frequently used predicates as NamedNodes
P = {
    # Atlas ontology
    "authored_by":    NamedNode(ATLAS + "authored_by"),
    "affiliated_with":NamedNode(ATLAS + "affiliated_with"),
    "cites":          NamedNode(ATLAS + "cites"),
    "extends":        NamedNode(ATLAS + "extends"),
    "published_in":   NamedNode(ATLAS + "published_in"),
    "published_by":   NamedNode(ATLAS + "published_by"),
    "has_doi":        NamedNode(ATLAS + "has_doi"),
    "has_arxiv_id":   NamedNode(ATLAS + "has_arxiv_id"),
    "has_isbn":       NamedNode(ATLAS + "has_isbn"),
    "has_issn":       NamedNode(ATLAS + "has_issn"),
    "has_pmid":       NamedNode(ATLAS + "has_pmid"),
    "has_orcid":      NamedNode(ATLAS + "has_orcid"),
    "has_gnd_id":     NamedNode(ATLAS + "has_gnd_id"),
    "has_rvk_class":  NamedNode(ATLAS + "has_rvk_class"),
    "has_gnd_keyword":NamedNode(ATLAS + "has_gnd_keyword"),
    "title":          NamedNode(ATLAS + "title"),
    "year":           NamedNode(ATLAS + "year"),
    "language":       NamedNode(ATLAS + "language"),
    # Standard
    "same_as":        NamedNode(OWL  + "sameAs"),
    "type":           NamedNode(RDF  + "type"),
    "label":          NamedNode(RDFS + "label"),
}

# RDF types
T = {
    "Document":    NamedNode(ATLAS + "Document"),
    "Paper":       NamedNode(ATLAS + "Paper"),
    "Book":        NamedNode(ATLAS + "Book"),
    "Thesis":      NamedNode(ATLAS + "Thesis"),
    "Report":      NamedNode(ATLAS + "Report"),
    "Author":      NamedNode(ATLAS + "Author"),
    "Institution": NamedNode(ATLAS + "Institution"),
    "Journal":     NamedNode(ATLAS + "Journal"),
    "Conference":  NamedNode(ATLAS + "Conference"),
}


# ── URI helpers ───────────────────────────────────────────────────────────────

def doc_uri(document_id: str) -> NamedNode:
    """Named node for a catalog document."""
    return NamedNode(ATLAS_D + document_id)


def doc_graph(document_id: str) -> NamedNode:
    """Named graph for a document — isolates its triples."""
    return NamedNode(ATLAS_D + document_id + "/graph")


def author_uri(name_slug: str) -> NamedNode:
    """Named node for an author (slug = normalised name)."""
    return NamedNode(ATLAS_A + name_slug)


def journal_uri(slug: str) -> NamedNode:
    return NamedNode(ATLAS_J + slug)


def wikidata_uri(qid: str) -> NamedNode:
    """e.g. wikidata_uri('Q42') → <https://www.wikidata.org/entity/Q42>"""
    q = qid.lstrip("Q")
    return NamedNode(WD + "Q" + q)


def orcid_uri(orcid: str) -> NamedNode:
    """e.g. orcid_uri('0000-0002-1825-0097') → <https://orcid.org/0000-0002-1825-0097>"""
    return NamedNode(ORCID + orcid.strip())


def doi_uri(doi: str) -> NamedNode:
    return NamedNode(DOI_URL + doi.strip().lstrip("https://doi.org/"))


def _slugify(text: str) -> str:
    """Convert a name/title to a URI-safe slug."""
    import re
    t = text.lower().strip()
    t = re.sub(r'[^a-z0-9]+', '_', t)
    return t.strip('_')[:80]


def author_uri_from_name(name: str) -> NamedNode:
    return author_uri(_slugify(name))


# ── Store wrapper ─────────────────────────────────────────────────────────────

class KnowledgeStore:
    """Thin wrapper around pyoxigraph.Store with Atlas-specific helpers.

    Usage:
        store = KnowledgeStore.open(catalog_root)
        with store:
            store.add_doc_triples(document_id, triples)
    """

    def __init__(self, store: Store) -> None:
        self._store = store

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    def open(cls, catalog_root: Path) -> "KnowledgeStore":
        """Open (or create) the knowledge store for a catalog."""
        path = catalog_root / ".atlas" / "knowledge"
        path.mkdir(parents=True, exist_ok=True)
        return cls(Store(str(path)))

    @classmethod
    def open_memory(cls) -> "KnowledgeStore":
        """In-memory store for testing."""
        return cls(Store())

    def close(self) -> None:
        pass  # pyoxigraph Store closes automatically

    def __enter__(self) -> "KnowledgeStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(
        self,
        subject: NamedNode,
        predicate: NamedNode,
        obj: NamedNode | Literal,
        graph: NamedNode | None = None,
    ) -> None:
        """Add a single quad to the store."""
        g = graph or DefaultGraph()
        self._store.add(Quad(subject, predicate, obj, g))

    def add_many(
        self,
        triples: list[tuple[NamedNode, NamedNode, NamedNode | Literal]],
        graph: NamedNode | None = None,
    ) -> None:
        """Add multiple triples to the same graph."""
        g = graph or DefaultGraph()
        for s, p, o in triples:
            self._store.add(Quad(s, p, o, g))

    def add_doc_triples(
        self,
        document_id: str,
        triples: list[tuple[NamedNode, NamedNode, NamedNode | Literal]],
    ) -> None:
        """Add triples to a document's named graph."""
        self.add_many(triples, graph=doc_graph(document_id))

    def remove_document(self, document_id: str) -> None:
        """Remove all triples for a document (its named graph)."""
        g = doc_graph(document_id)
        self._store.remove_graph(g)

    # ── Read ──────────────────────────────────────────────────────────────────

    def query(self, sparql: str) -> list[dict]:
        """Execute a SELECT query, return list of binding dicts."""
        results = self._store.query(sparql)
        return [
            {k: v for k, v in row.items()}
            for row in results
        ]

    def triples_for_doc(
        self, document_id: str
    ) -> Iterator[Quad]:
        """Iterate all quads in a document's named graph."""
        g = doc_graph(document_id)
        return self._store.quads_for_pattern(None, None, None, g)

    def has_document(self, document_id: str) -> bool:
        """True if the store has any triples for this document."""
        g = doc_graph(document_id)
        return any(True for _ in self._store.quads_for_pattern(
            None, None, None, g
        ))

    # ── Literals ─────────────────────────────────────────────────────────────

    @staticmethod
    def lit(value: str, lang: str | None = None) -> Literal:
        if lang:
            return Literal(str(value), language=lang)
        return Literal(str(value))

    @staticmethod
    def int_lit(value: int) -> Literal:
        return Literal(str(value), datatype=NamedNode(
            "http://www.w3.org/2001/XMLSchema#integer"
        ))
