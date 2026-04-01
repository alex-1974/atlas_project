# src/atlas/enrich/crossref.py
"""CrossRef enrichment — fetch full metadata for documents with a DOI.

CrossRef (api.crossref.org) provides:
  - Normalised title, authors with affiliations
  - Journal name, ISSN, volume/issue/pages
  - Publication date
  - Reference list (for building cites-triples)
  - Citation count

No API key required. Rate limit: 50 requests/second for the public API,
more with a registered email (Polite Pool via mailto parameter).

Relationship to Wikidata enrichment:
  - Wikidata is primary for identifier resolution and owl:sameAs
  - CrossRef is primary for full bibliographic metadata and references
  - If a DOI is known, run CrossRef first (metadata), then Wikidata (QID)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import logging

log = logging.getLogger(__name__)

_API_BASE   = "https://api.crossref.org/works/"
_USER_AGENT = "Atlas/2.0 (atlas-catalog; mailto:atlas@local) Python"
_SLEEP      = 0.5


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_by_doi(doi: str) -> dict | None:
    """Fetch CrossRef metadata for a DOI.

    Returns a normalised dict or None if the DOI is not found.

    Returned keys (all optional):
        title, authors, year, journal, volume, issue, pages,
        publisher, issn, doi, references (list of {doi, title, author})
    """
    url = _API_BASE + urllib.parse.quote(doi.strip(), safe="") + "?mailto=atlas@local"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("CrossRef request failed for %s: %s", doi, exc)
        return None

    work = raw.get("message", {})
    if not work:
        return None

    return _normalise(work)


def enrich_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> dict | None:
    """Fetch CrossRef metadata for a document and write it to SQLite.

    Updates: title, authors, year, journal, volume, issue, pages,
             publisher in the documents table (COALESCE — only fills gaps).

    Returns the normalised metadata dict, or None if no DOI or no result.
    """
    row = conn.execute(
        "SELECT doi FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not row or not row["doi"]:
        return None

    meta = fetch_by_doi(row["doi"])
    if not meta:
        return None

    _write_to_db(conn, document_id, meta)
    time.sleep(_SLEEP)
    return meta


def enrich_all(
    conn: sqlite3.Connection,
    limit: int | None = None,
) -> list[dict]:
    """Enrich all documents that have a DOI but incomplete metadata."""
    rows = conn.execute(
        """
        SELECT document_id FROM documents
        WHERE doi IS NOT NULL AND doi != ''
        ORDER BY added_at
        """
    ).fetchall()

    results = []
    for i, row in enumerate(rows):
        if limit is not None and i >= limit:
            break
        meta = enrich_document(conn, row["document_id"])
        if meta:
            meta["document_id"] = row["document_id"]
            results.append(meta)

    return results


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalise(work: dict) -> dict:
    """Convert CrossRef work object to a clean Atlas metadata dict."""
    result: dict = {}

    # Title
    titles = work.get("title", [])
    if titles:
        result["title"] = titles[0].strip()

    # Authors
    authors = []
    for a in work.get("author", []):
        given  = a.get("given", "").strip()
        family = a.get("family", "").strip()
        if family:
            name = f"{given} {family}".strip() if given else family
            entry: dict = {"name": name}
            if a.get("ORCID"):
                orcid = re.sub(r'https?://orcid\.org/', '', a["ORCID"])
                entry["orcid"] = orcid
            if a.get("affiliation"):
                entry["affiliation"] = a["affiliation"][0].get("name", "")
            authors.append(entry)
    if authors:
        result["authors"] = authors

    # Year
    date_parts = (
        work.get("published-print", {}).get("date-parts")
        or work.get("published-online", {}).get("date-parts")
        or work.get("issued", {}).get("date-parts")
    )
    if date_parts and date_parts[0]:
        result["year"] = int(date_parts[0][0])

    # Journal
    container = work.get("container-title", [])
    if container:
        result["journal"] = container[0].strip()

    # ISSN
    issns = work.get("ISSN", [])
    if issns:
        result["issn"] = issns[0]

    # Volume / issue / pages
    for key in ("volume", "issue", "page"):
        val = work.get(key)
        if val:
            result[key] = str(val)

    # Publisher
    if work.get("publisher"):
        result["publisher"] = work["publisher"]

    # DOI (normalised)
    if work.get("DOI"):
        result["doi"] = work["DOI"].lower()

    # References
    refs = []
    for ref in work.get("reference", [])[:50]:  # cap at 50
        entry: dict = {}
        if ref.get("DOI"):
            entry["doi"] = ref["DOI"].lower()
        if ref.get("article-title"):
            entry["title"] = ref["article-title"]
        if ref.get("author"):
            entry["author"] = ref["author"]
        if entry:
            refs.append(entry)
    if refs:
        result["references"] = refs

    return result


# ── Database write ────────────────────────────────────────────────────────────

def _write_to_db(
    conn: sqlite3.Connection,
    document_id: str,
    meta: dict,
) -> None:
    """Write CrossRef metadata to documents table, filling gaps only."""
    updates: list[tuple[str, object]] = []

    if meta.get("title"):
        updates.append(("title = COALESCE(NULLIF(title,''), ?)", meta["title"]))

    if meta.get("authors"):
        authors_json = json.dumps(
            [a["name"] for a in meta["authors"]], ensure_ascii=False
        )
        updates.append((
            "authors = COALESCE(NULLIF(authors,''), ?)", authors_json
        ))

    if meta.get("year"):
        updates.append(("year = COALESCE(year, ?)", meta["year"]))

    for col in ("journal", "volume", "issue", "publisher"):
        if meta.get(col):
            updates.append((
                f"{col} = COALESCE(NULLIF({col},''), ?)", meta[col]
            ))

    if not updates:
        return

    set_clause = ", ".join(expr for expr, _ in updates)
    values     = [val for _, val in updates]
    conn.execute(
        f"UPDATE documents SET {set_clause} WHERE document_id = ?",
        (*values, document_id),
    )
    conn.commit()
