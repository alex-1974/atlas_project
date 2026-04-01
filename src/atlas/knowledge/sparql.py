# src/atlas/knowledge/sparql.py
"""SPARQL query library for Atlas CLI commands.

All queries use GRAPH ?g { ... } to search across named graphs.
Atlas stores triples in named graphs (one per document) — without
GRAPH wrapping, queries against the default graph return nothing.
"""
from __future__ import annotations

from atlas.knowledge.store import KnowledgeStore, ATLAS, ATLAS_D, ATLAS_A


# ── References ────────────────────────────────────────────────────────────────

def references_for_document(
    store: KnowledgeStore,
    document_id: str,
    depth: int = 1,
) -> list[dict]:
    """Return documents cited by document_id (depth=1 or 2)."""
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
  GRAPH ?g {{
    <{uri}> atlas:cites ?cited .
    OPTIONAL {{ ?cited atlas:title ?title . }}
    OPTIONAL {{ ?cited atlas:has_doi ?doi . }}
    OPTIONAL {{ ?cited owl:sameAs ?sameAs . }}
  }}
}}
"""
            rows = store.query(sparql)
            for row in rows:
                cited_uri = _node_str(row.get("cited"))
                if not cited_uri or cited_uri in visited:
                    continue
                visited.add(cited_uri)
                local_id = cited_uri[len(ATLAS_D):] if cited_uri.startswith(ATLAS_D) else None
                results.append({
                    "uri":         cited_uri,
                    "title":       _str(row.get("title")),
                    "doi":         _str(row.get("doi")),
                    "wikidata":    _node_str(row.get("sameAs")),
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
    """Return documents that cite document_id."""
    doc_uri = ATLAS_D + document_id
    sparql = f"""
PREFIX atlas: <{ATLAS}>
SELECT DISTINCT ?source ?title WHERE {{
  GRAPH ?g {{
    ?source atlas:cites <{doc_uri}> .
    OPTIONAL {{ ?source atlas:title ?title . }}
  }}
}}
"""
    rows = store.query(sparql)
    results = []
    for row in rows:
        source_uri = _node_str(row.get("source"))
        local_id   = source_uri[len(ATLAS_D):] if source_uri.startswith(ATLAS_D) else None
        results.append({
            "uri":         source_uri,
            "title":       _str(row.get("title")),
            "document_id": local_id,
        })
    return results


# ── Authors & Co-authorship ───────────────────────────────────────────────────

def coauthors_of(store: KnowledgeStore, author_name: str) -> list[dict]:
    """Return co-authors of a named author."""
    name_lower = author_name.lower()
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?paper ?coauthor ?coauthorLabel WHERE {{
  GRAPH ?g {{
    ?author rdfs:label ?authorLabel .
    FILTER(LCASE(STR(?authorLabel)) = "{name_lower}")
    ?paper atlas:authored_by ?author .
    ?paper atlas:authored_by ?coauthor .
    FILTER(?coauthor != ?author)
    OPTIONAL {{ ?coauthor rdfs:label ?coauthorLabel . }}
  }}
}}
"""
    rows = store.query(sparql)
    counts: dict[str, dict] = {}
    for row in rows:
        uri   = _node_str(row.get("coauthor"))
        label = _str(row.get("coauthorLabel")) or uri
        if uri not in counts:
            counts[uri] = {"name": label, "uri": uri, "shared_papers": 0}
        counts[uri]["shared_papers"] += 1
    return sorted(counts.values(), key=lambda x: -x["shared_papers"])


def documents_by_author(store: KnowledgeStore, author_name: str) -> list[dict]:
    """Return all documents by a named author."""
    name_lower = author_name.lower()
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?paper ?title ?year WHERE {{
  GRAPH ?g {{
    ?author rdfs:label ?authorLabel .
    FILTER(LCASE(STR(?authorLabel)) = "{name_lower}")
    ?paper atlas:authored_by ?author .
    OPTIONAL {{ ?paper atlas:title ?title . }}
    OPTIONAL {{ ?paper atlas:year  ?year  . }}
  }}
}}
ORDER BY DESC(?year)
"""
    rows = store.query(sparql)
    results = []
    for row in rows:
        uri = _node_str(row.get("paper"))
        local_id = uri[len(ATLAS_D):] if uri.startswith(ATLAS_D) else None
        results.append({
            "uri":         uri,
            "document_id": local_id,
            "title":       _str(row.get("title")),
            "year":        _int(row.get("year")),
        })
    return results


# ── Concepts ──────────────────────────────────────────────────────────────────

def documents_about_concept(store: KnowledgeStore, concept: str) -> list[dict]:
    """Return documents related to a concept."""
    concept_lower = concept.lower()
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?paper ?title ?rel WHERE {{
  GRAPH ?g {{
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
}}
"""
    rows = store.query(sparql)
    results = []
    for row in rows:
        uri      = _node_str(row.get("paper"))
        local_id = uri[len(ATLAS_D):] if uri.startswith(ATLAS_D) else None
        results.append({
            "uri":         uri,
            "document_id": local_id,
            "title":       _str(row.get("title")),
            "relation":    _str(row.get("rel")),
        })
    return results


# ── Wikidata linkage ──────────────────────────────────────────────────────────

def wikidata_qid_for_document(store: KnowledgeStore, document_id: str) -> str | None:
    """Return the Wikidata QID for a document, if available."""
    doc_uri = ATLAS_D + document_id
    sparql = f"""
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?qid WHERE {{
  GRAPH ?g {{
    <{doc_uri}> owl:sameAs ?qid .
    FILTER(STRSTARTS(STR(?qid), "https://www.wikidata.org/entity/Q"))
  }}
}}
LIMIT 1
"""
    rows = store.query(sparql)
    if rows:
        return _node_str(rows[0].get("qid"))
    return None


def orcids_for_document(store: KnowledgeStore, document_id: str) -> list[dict]:
    """Return authors with ORCIDs for a document."""
    doc_uri = ATLAS_D + document_id
    sparql = f"""
PREFIX atlas: <{ATLAS}>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?author ?name ?orcid WHERE {{
  GRAPH ?g {{
    <{doc_uri}> atlas:authored_by ?author .
    OPTIONAL {{ ?author rdfs:label ?name . }}
    OPTIONAL {{ ?author atlas:has_orcid ?orcid . }}
  }}
}}
"""
    rows = store.query(sparql)
    return [
        {
            "name":  _str(row.get("name")),
            "orcid": _str(row.get("orcid")),
            "uri":   _node_str(row.get("author")),
        }
        for row in rows
    ]


# ── Catalog statistics ────────────────────────────────────────────────────────

def graph_stats(store: KnowledgeStore) -> dict:
    """Return basic statistics about the knowledge graph."""
    # Use UNION for document subclasses — IN() with URIs causes parse errors
    # in some Oxigraph versions
    doc_union = " UNION ".join(
        f"{{ ?d a <{ATLAS}{t}> . }}"
        for t in ["Document", "Paper", "Book", "Thesis", "Report", "Chapter"]
    )
    queries = {
        "documents": f"SELECT (COUNT(DISTINCT ?d) AS ?n) WHERE {{ GRAPH ?g {{ {doc_union} }} }}",
        "authors":   f"SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE {{ GRAPH ?g {{ ?a a <{ATLAS}Author> . }} }}",
        "citations": f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ ?d <{ATLAS}cites> ?c . }} }}",
        "wikidata":  f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ ?d <http://www.w3.org/2002/07/owl#sameAs> ?q . FILTER(STRSTARTS(STR(?q), 'https://www.wikidata.org')) }} }}",
        "orcids":    f"SELECT (COUNT(DISTINCT ?o) AS ?n) WHERE {{ GRAPH ?g {{ ?a <{ATLAS}has_orcid> ?o . }} }}",
    }
    stats = {}
    for key, sparql in queries.items():
        try:
            rows = store.query(sparql)
            stats[key] = _int(rows[0].get("n")) if rows else 0
        except Exception:
            stats[key] = 0
    return stats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str(val: object) -> str:
    """Extract string value from a pyoxigraph Literal or NamedNode."""
    if val is None:
        return ""
    if hasattr(val, 'value'):
        return str(val.value)
    s = str(val)
    s = s.strip('"').split('"')[0].split('@')[0].split('^^')[0]
    s = s.strip('<>')
    return s.strip()


def _node_str(val: object) -> str:
    """Extract URI string from a pyoxigraph NamedNode."""
    if val is None:
        return ""
    if hasattr(val, 'value'):
        return str(val.value)
    return str(val).strip('<>')


def _int(val: object) -> int | None:
    s = _str(val)
    try:
        return int(s)
    except (ValueError, TypeError):
        return None
