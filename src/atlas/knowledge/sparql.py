# src/atlas/knowledge/sparql.py
"""SPARQL query library for Atlas CLI commands.

Each function corresponds to one CLI command that reads from the
knowledge graph:

    atlas refs <id>          → references_for_document()
    atlas graph --author X   → coauthors_of()
    atlas concept "X"        → documents_about_concept()
    atlas similar --graph    → documents_by_author()

All functions return plain Python dicts/lists — no RDF types leak
out of this module.  The KnowledgeStore handles the pyoxigraph layer.
"""
from __future__ import annotations

from atlas.knowledge.store import KnowledgeStore, ATLAS, ATLAS_D, ATLAS_A


# ── References ────────────────────────────────────────────────────────────────

def references_for_document(
    store: KnowledgeStore,
    document_id: str,
    depth: int = 1,
) -> list[dict]:
    """Return documents cited by document_id.

    depth=1: direct citations only
    depth=2: citations of citations

    Each result dict:
        {"uri": str, "title": str|None, "doi": str|None,
         "document_id": str|None, "depth": int}
    """
    doc_uri = ATLAS_D + document_id
    results = []
    visited: set[str] = {doc_uri}

    def _fetch_level(uris: list[str], current_depth: int) -> list[str]:
        if current_depth > depth or not uris:
            return []
        next_uris = []
        for uri in uris:
            sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
SELECT DISTINCT ?cited ?title ?doi ?sameAs WHERE {{
  <{uri}> atlas:cites ?cited .
  OPTIONAL {{ ?cited atlas:title ?title . }}
  OPTIONAL {{ ?cited atlas:has_doi ?doi . }}
  OPTIONAL {{ ?cited owl:sameAs ?sameAs . }}
}}
"""
            rows = store.query(sparql)
            for row in rows:
                cited_uri = str(row.get("cited", ""))
                if cited_uri in visited:
                    continue
                visited.add(cited_uri)
                # Try to map back to a local document_id
                local_id = None
                if cited_uri.startswith(ATLAS_D):
                    candidate = cited_uri[len(ATLAS_D):]
                    # Remove /graph suffix if present
                    candidate = candidate.rstrip("/graph")
                    local_id = candidate

                results.append({
                    "uri":         cited_uri,
                    "title":       _str(row.get("title")),
                    "doi":         _str(row.get("doi")),
                    "wikidata":    _str(row.get("sameAs")),
                    "document_id": local_id,
                    "depth":       current_depth,
                })
                next_uris.append(cited_uri)
        return next_uris

    next_level = _fetch_level([doc_uri], 1)
    if depth >= 2:
        _fetch_level(next_level, 2)

    return results


def citing_documents(
    store: KnowledgeStore,
    document_id: str,
) -> list[dict]:
    """Return documents that cite document_id (reverse citations)."""
    doc_uri = ATLAS_D + document_id
    sparql = f"""
PREFIX atlas: <{ATLAS}>
SELECT DISTINCT ?source ?title WHERE {{
  ?source atlas:cites <{doc_uri}> .
  OPTIONAL {{ ?source atlas:title ?title . }}
}}
"""
    rows = store.query(sparql)
    results = []
    for row in rows:
        source_uri = str(row.get("source", ""))
        local_id   = source_uri[len(ATLAS_D):] if source_uri.startswith(ATLAS_D) else None
        results.append({
            "uri":         source_uri,
            "title":       _str(row.get("title")),
            "document_id": local_id,
        })
    return results


# ── Authors & Co-authorship ───────────────────────────────────────────────────

def coauthors_of(
    store: KnowledgeStore,
    author_name: str,
) -> list[dict]:
    """Return co-authors of a named author.

    Matches by label substring (case-insensitive).
    Returns list of {"name": str, "uri": str, "shared_papers": int}
    """
    name_lower = author_name.lower()
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?paper ?coauthor ?coauthorLabel WHERE {{
  ?author rdfs:label ?authorLabel .
  FILTER(LCASE(STR(?authorLabel)) = "{name_lower}")
  ?paper atlas:authored_by ?author .
  ?paper atlas:authored_by ?coauthor .
  FILTER(?coauthor != ?author)
  OPTIONAL {{ ?coauthor rdfs:label ?coauthorLabel . }}
}}
"""
    rows = store.query(sparql)
    counts: dict[str, dict] = {}
    for row in rows:
        uri   = str(row.get("coauthor", ""))
        label = _str(row.get("coauthorLabel")) or uri
        if uri not in counts:
            counts[uri] = {"name": label, "uri": uri, "shared_papers": 0}
        counts[uri]["shared_papers"] += 1

    return sorted(counts.values(), key=lambda x: -x["shared_papers"])


def documents_by_author(
    store: KnowledgeStore,
    author_name: str,
) -> list[dict]:
    """Return all documents by a named author."""
    name_lower = author_name.lower()
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?paper ?title ?year WHERE {{
  ?author rdfs:label ?authorLabel .
  FILTER(LCASE(STR(?authorLabel)) = "{name_lower}")
  ?paper atlas:authored_by ?author .
  OPTIONAL {{ ?paper atlas:title ?title . }}
  OPTIONAL {{ ?paper atlas:year  ?year  . }}
}}
ORDER BY DESC(?year)
"""
    rows = store.query(sparql)
    results = []
    for row in rows:
        uri = str(row.get("paper", ""))
        local_id = uri[len(ATLAS_D):] if uri.startswith(ATLAS_D) else None
        results.append({
            "uri":         uri,
            "document_id": local_id,
            "title":       _str(row.get("title")),
            "year":        _int(row.get("year")),
        })
    return results


# ── Concepts ──────────────────────────────────────────────────────────────────

def documents_about_concept(
    store: KnowledgeStore,
    concept: str,
) -> list[dict]:
    """Return documents related to a concept (atlas:about or atlas:introduces).

    Matches concept URIs containing the search term (case-insensitive)
    or by rdfs:label.
    """
    concept_lower = concept.lower()
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?paper ?title ?rel WHERE {{
  {{
    ?paper atlas:about ?concept .
    BIND("about" AS ?rel)
  }} UNION {{
    ?paper atlas:introduces ?concept .
    BIND("introduces" AS ?rel)
  }} UNION {{
    ?paper atlas:uses_method ?concept .
    BIND("uses_method" AS ?rel)
  }}
  FILTER(
    CONTAINS(LCASE(STR(?concept)), "{concept_lower}") ||
    EXISTS {{
      ?concept rdfs:label ?label .
      FILTER(CONTAINS(LCASE(STR(?label)), "{concept_lower}"))
    }}
  )
  OPTIONAL {{ ?paper atlas:title ?title . }}
}}
"""
    rows = store.query(sparql)
    results = []
    for row in rows:
        uri      = str(row.get("paper", ""))
        local_id = uri[len(ATLAS_D):] if uri.startswith(ATLAS_D) else None
        results.append({
            "uri":         uri,
            "document_id": local_id,
            "title":       _str(row.get("title")),
            "relation":    _str(row.get("rel")),
        })
    return results


# ── Wikidata linkage ──────────────────────────────────────────────────────────

def wikidata_qid_for_document(
    store: KnowledgeStore,
    document_id: str,
) -> str | None:
    """Return the Wikidata QID for a document, if available."""
    doc_uri = ATLAS_D + document_id
    sparql = f"""
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?qid WHERE {{
  <{doc_uri}> owl:sameAs ?qid .
  FILTER(STRSTARTS(STR(?qid), "https://www.wikidata.org/entity/Q"))
}}
LIMIT 1
"""
    rows = store.query(sparql)
    if rows:
        return str(rows[0].get("qid", ""))
    return None


def orcids_for_document(
    store: KnowledgeStore,
    document_id: str,
) -> list[dict]:
    """Return authors with ORCIDs for a document."""
    doc_uri = ATLAS_D + document_id
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?author ?name ?orcid WHERE {{
  <{doc_uri}> atlas:authored_by ?author .
  OPTIONAL {{ ?author rdfs:label ?name . }}
  OPTIONAL {{ ?author atlas:has_orcid ?orcid . }}
}}
"""
    rows = store.query(sparql)
    return [
        {
            "name":  _str(row.get("name")),
            "orcid": _str(row.get("orcid")),
            "uri":   str(row.get("author", "")),
        }
        for row in rows
    ]


# ── Catalog statistics ────────────────────────────────────────────────────────

def graph_stats(store: KnowledgeStore) -> dict:
    """Return basic statistics about the knowledge graph."""
    queries = {
        "documents":  f"SELECT (COUNT(DISTINCT ?d) AS ?n) WHERE {{ ?d a <{ATLAS}Document> . }}",
        "authors":    f"SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE {{ ?a a <{ATLAS}Author> . }}",
        "citations":  f"SELECT (COUNT(*) AS ?n) WHERE {{ ?d <{ATLAS}cites> ?c . }}",
        "wikidata":   "SELECT (COUNT(*) AS ?n) WHERE { ?d <http://www.w3.org/2002/07/owl#sameAs> ?q . FILTER(STRSTARTS(STR(?q), \"https://www.wikidata.org\")) }",
        "orcids":     f"SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE {{ ?a <{ATLAS}has_orcid> ?o . }}",
    }
    stats = {}
    for key, sparql in queries.items():
        rows = store.query(sparql)
        stats[key] = _int(rows[0].get("n")) if rows else 0
    return stats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str(val: object) -> str:
    if val is None:
        return ""
    s = str(val)
    # Strip RDF literal quotes: "value"@en or "value"^^xsd:type
    s = s.strip('"').split('"')[0].split('@')[0].split('^^')[0]
    return s.strip()


def _int(val: object) -> int | None:
    s = _str(val)
    try:
        return int(s)
    except (ValueError, TypeError):
        return None
