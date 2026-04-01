# src/atlas/enrich/wikidata.py
"""Wikidata enrichment — resolve documents to Wikidata QIDs.

Wikidata is the primary external identifier hub for Atlas:
  DOI   → Wikidata QID (P356)   → author ORCIDs (P496)
  ISBN  → Wikidata QID (P212)   → journal ISSN (P236)
  Title → Wikidata search API   → QID + metadata

All queries go through the public Wikidata SPARQL endpoint
(query.wikidata.org) or the REST search API (www.wikidata.org/w/api.php).
Both are free, require no API key, and allow reasonable request rates.

Rate limiting: Wikidata asks for a maximum of ~5 requests/second and
a descriptive User-Agent.  We use a conservative 0.5s sleep between
requests and identify as "Atlas/2.0 (atlas-catalog; Python)".

Offline mode: if the network is unavailable, all functions return empty
results gracefully — Atlas continues to work, just without enrichment.
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
import json
import re
import sqlite3
import logging

from pyoxigraph import NamedNode, Literal

from atlas.knowledge.store import (
    KnowledgeStore, P, T,
    doc_uri, author_uri_from_name, wikidata_uri, orcid_uri,
    journal_uri, _slugify,
)

log = logging.getLogger(__name__)

_USER_AGENT = "Atlas/2.0 (atlas-catalog; https://github.com/atlas-catalog) Python"
_SPARQL_URL = "https://query.wikidata.org/sparql"
_API_URL    = "https://www.wikidata.org/w/api.php"
_SLEEP      = 0.6   # seconds between requests


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_document(
    conn: sqlite3.Connection,
    store: KnowledgeStore,
    document_id: str,
) -> dict:
    """Enrich one document with Wikidata data.

    Resolution order:
    1. DOI → Wikidata SPARQL (most reliable)
    2. ISBN → Wikidata SPARQL
    3. arXiv-ID → Wikidata SPARQL
    4. Title + first author → Wikidata search API (fallback, less reliable)

    Writes owl:sameAs and author ORCID triples to the store.
    Updates documents.authors if ORCID-disambiguated names are richer.

    Returns a summary dict:
        {"qid": "Q12345", "orcids": {"name": "0000-...", ...}, "source": "doi"}
    """
    row = conn.execute(
        "SELECT doi, isbn, arxiv_id, title, authors FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not row:
        return {}

    result: dict = {}

    # Try DOI first
    if row["doi"]:
        qid = _doi_to_qid(row["doi"])
        if qid:
            result = {"qid": qid, "source": "doi"}

    # Try ISBN
    if not result and row["isbn"]:
        qid = _isbn_to_qid(row["isbn"])
        if qid:
            result = {"qid": qid, "source": "isbn"}

    # Try arXiv
    if not result and row["arxiv_id"]:
        qid = _arxiv_to_qid(row["arxiv_id"])
        if qid:
            result = {"qid": qid, "source": "arxiv"}

    # Fallback: title search
    if not result and row["title"]:
        authors = _parse_authors(row["authors"])
        first_author = authors[0] if authors else None
        qid = _title_search(row["title"], first_author)
        if qid:
            result = {"qid": qid, "source": "title_search"}

    if not result:
        log.debug("No Wikidata match for %s", document_id)
        return {}

    qid = result["qid"]
    qid_node = wikidata_uri(qid)
    doc = doc_uri(document_id)

    triples: list[tuple[NamedNode, NamedNode, NamedNode | Literal]] = []

    # owl:sameAs to Wikidata
    triples.append((doc, P["same_as"], qid_node))

    # Fetch detailed metadata from Wikidata
    details = _fetch_item_details(qid)
    orcids: dict[str, str] = {}

    if details:
        # Authors with ORCIDs
        for author_info in details.get("authors", []):
            name  = author_info.get("name", "")
            orcid = author_info.get("orcid", "")
            author_qid = author_info.get("qid", "")

            if not name:
                continue
            a_node = author_uri_from_name(name)
            triples.append((doc,    P["authored_by"], a_node))
            triples.append((a_node, P["type"],        T["Author"]))
            triples.append((a_node, P["label"],       KnowledgeStore.lit(name)))

            if orcid:
                orcids[name] = orcid
                orcid_node = orcid_uri(orcid)
                triples.append((a_node, P["same_as"],  orcid_node))
                triples.append((a_node, P["has_orcid"],KnowledgeStore.lit(orcid)))

            if author_qid:
                triples.append((a_node, P["same_as"], wikidata_uri(author_qid)))

        # Journal/venue
        if details.get("journal_qid"):
            j_node = NamedNode("https://www.wikidata.org/entity/" + details["journal_qid"])
            triples.append((doc, P["published_in"], j_node))
            if details.get("journal_name"):
                triples.append((j_node, P["label"],
                                KnowledgeStore.lit(details["journal_name"])))
            if details.get("issn"):
                triples.append((j_node, P["has_issn"],
                                KnowledgeStore.lit(details["issn"])))

        # Year from Wikidata (may be more reliable than extracted)
        if details.get("year"):
            triples.append((doc, P["year"],
                            KnowledgeStore.int_lit(details["year"])))

    store.add_doc_triples(document_id, triples)
    result["orcids"] = orcids
    return result


def enrich_all(
    conn: sqlite3.Connection,
    store: KnowledgeStore,
    limit: int | None = None,
) -> list[dict]:
    """Enrich all documents that do not yet have a Wikidata QID.

    Returns a list of result dicts (one per document processed).
    """
    rows = conn.execute(
        "SELECT document_id FROM documents ORDER BY added_at",
    ).fetchall()

    results = []
    for i, row in enumerate(rows):
        if limit is not None and i >= limit:
            break
        doc_id = row["document_id"]

        # Skip if already enriched
        if store.has_document(doc_id):
            doc = doc_uri(doc_id)
            already = list(store._store.quads_for_pattern(
                doc, P["same_as"], None, None
            ))
            if any("wikidata.org" in str(q.object) for q in already):
                log.debug("Skipping %s (already has Wikidata QID)", doc_id[:12])
                continue

        result = enrich_document(conn, store, doc_id)
        result["document_id"] = doc_id
        results.append(result)
        time.sleep(_SLEEP)

    return results


# ── Wikidata queries ──────────────────────────────────────────────────────────

def _doi_to_qid(doi: str) -> str | None:
    """Find Wikidata QID for a DOI (P356)."""
    doi_clean = doi.strip().upper()
    sparql = f"""
SELECT ?item WHERE {{
  ?item wdt:P356 "{doi_clean}" .
}}
LIMIT 1
"""
    rows = _sparql(sparql)
    if rows:
        return _extract_qid(rows[0].get("item", ""))
    return None


def _isbn_to_qid(isbn: str) -> str | None:
    """Find Wikidata QID for an ISBN (P212 = ISBN-13, P957 = ISBN-10)."""
    isbn_clean = re.sub(r'[^0-9X]', '', isbn.upper())
    sparql = f"""
SELECT ?item WHERE {{
  {{ ?item wdt:P212 "{isbn_clean}" }} UNION
  {{ ?item wdt:P957 "{isbn_clean}" }}
}}
LIMIT 1
"""
    rows = _sparql(sparql)
    if rows:
        return _extract_qid(rows[0].get("item", ""))
    return None


def _arxiv_to_qid(arxiv_id: str) -> str | None:
    """Find Wikidata QID for an arXiv ID (P818)."""
    arxiv_clean = arxiv_id.strip()
    sparql = f"""
SELECT ?item WHERE {{
  ?item wdt:P818 "{arxiv_clean}" .
}}
LIMIT 1
"""
    rows = _sparql(sparql)
    if rows:
        return _extract_qid(rows[0].get("item", ""))
    return None


def _title_search(title: str, first_author: str | None = None) -> str | None:
    """Search Wikidata by title using the MediaWiki API.

    Less reliable than identifier-based lookup — only use as fallback.
    Requires the title to match closely and optional author to disambiguate.
    """
    params = {
        "action":   "wbsearchentities",
        "search":   title[:100],
        "language": "en",
        "type":     "item",
        "limit":    "5",
        "format":   "json",
    }
    data = _api_get(params)
    if not data:
        return None

    candidates = data.get("search", [])
    if not candidates:
        return None

    # Simple heuristic: first result whose description mentions "article",
    # "paper", "book", or "publication"
    keywords = {"article", "paper", "book", "publication", "scholarly"}
    for c in candidates:
        desc = (c.get("description") or "").lower()
        if any(kw in desc for kw in keywords):
            return _extract_qid(c.get("id", ""))

    # Fall back to first result if it looks like a publication
    return _extract_qid(candidates[0].get("id", "")) if candidates else None


def _fetch_item_details(qid: str) -> dict:
    """Fetch detailed metadata for a Wikidata item.

    Returns:
        {
            "authors": [{"name": ..., "orcid": ..., "qid": ...}],
            "journal_qid": ...,
            "journal_name": ...,
            "issn": ...,
            "year": ...,
        }
    """
    sparql = f"""
SELECT ?author ?authorLabel ?orcid ?authorQid
       ?journal ?journalLabel ?issn ?pubDate
WHERE {{
  OPTIONAL {{
    wd:{qid} wdt:P50 ?authorNode .
    BIND(STR(?authorNode) AS ?authorQid)
    ?authorNode rdfs:label ?authorLabel .
    FILTER(LANG(?authorLabel) = "en")
    OPTIONAL {{ ?authorNode wdt:P496 ?orcid . }}
  }}
  OPTIONAL {{
    wd:{qid} wdt:P1433 ?journal .
    ?journal rdfs:label ?journalLabel .
    FILTER(LANG(?journalLabel) = "en")
    OPTIONAL {{ ?journal wdt:P236 ?issn . }}
  }}
  OPTIONAL {{
    wd:{qid} wdt:P577 ?pubDate .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""
    rows = _sparql(sparql)
    if not rows:
        return {}

    authors: list[dict] = []
    seen_authors: set[str] = set()
    journal_qid = journal_name = issn = None
    year = None

    for row in rows:
        # Author
        a_qid = _extract_qid(row.get("authorQid", ""))
        a_label = _str_val(row.get("authorLabel"))
        if a_label and a_qid and a_qid not in seen_authors:
            seen_authors.add(a_qid)
            authors.append({
                "name":  a_label,
                "orcid": _str_val(row.get("orcid")),
                "qid":   a_qid,
            })

        # Journal
        if not journal_qid and row.get("journal"):
            journal_qid  = _extract_qid(str(row["journal"]))
            journal_name = _str_val(row.get("journalLabel"))
            issn         = _str_val(row.get("issn"))

        # Year
        if not year and row.get("pubDate"):
            raw = _str_val(row["pubDate"])
            m = re.search(r'\d{4}', raw or "")
            if m:
                year = int(m.group(0))

    return {
        "authors":      authors,
        "journal_qid":  journal_qid,
        "journal_name": journal_name,
        "issn":         issn,
        "year":         year,
    }


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _sparql(query: str, timeout: int = 15) -> list[dict]:
    """Execute a Wikidata SPARQL query, return list of binding dicts."""
    url = _SPARQL_URL + "?" + urllib.parse.urlencode({
        "query":  query,
        "format": "json",
    })
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        bindings = data.get("results", {}).get("bindings", [])
        return [
            {k: v.get("value") for k, v in row.items()}
            for row in bindings
        ]
    except Exception as exc:
        log.debug("Wikidata SPARQL failed: %s", exc)
        return []


def _api_get(params: dict, timeout: int = 10) -> dict | None:
    """GET request to the Wikidata MediaWiki API."""
    url = _API_URL + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("Wikidata API failed: %s", exc)
        return None


def _extract_qid(uri_or_id: str) -> str:
    """Extract QID from a Wikidata URI or plain ID string."""
    if not uri_or_id:
        return ""
    m = re.search(r'(Q\d+)', uri_or_id)
    return m.group(1) if m else ""


def _str_val(val: object) -> str:
    """Safely convert a SPARQL binding value to string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


def _parse_authors(authors_json: str | None) -> list[str]:
    if not authors_json:
        return []
    try:
        parsed = json.loads(authors_json)
        return [a for a in parsed if isinstance(a, str) and a.strip()]
    except (json.JSONDecodeError, TypeError):
        return []
