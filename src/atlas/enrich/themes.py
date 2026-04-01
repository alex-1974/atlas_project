# src/atlas/enrich/themes.py
"""Themenextraktion — übergeordnete Konzepte aus Keywords, RVK und Wikidata.

Keywords (YAKE/KeyBERT) sind einzelne Terme: 'Hallenhaus', 'burgage plots'.
Themen sind übergeordnete Konzepte:  'Historische Bauforschung', 'Stadtmorphologie'.
RVK-Notationen sind bibliothekarische Klassifikationen: 'ZH 5500'.

Extraktionskette (in dieser Priorität):
    1. Wikidata main_subject (P921) — wenn QID bekannt: zuverlässigste Quelle
    2. RVK-Label aus gespeicherter Notation — wenn RVK bereits angereichert
    3. Keywords → RVK-API-Suche — Keywords als Suchanfrage, top-1 Notation
    4. Fallback: mehrteilige Keywords direkt als Themen verwenden

Ergebnis:
    - documents.subjects (JSON-Array) — neu in Migration 0013
    - Oxigraph: atlas:about Tripel mit subject-Knoten
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import urllib.parse
import urllib.request

from pyoxigraph import NamedNode

log = logging.getLogger(__name__)

_USER_AGENT = "Atlas/2.0 (atlas-catalog) Python"
_RVK_API    = "https://rvk.uni-regensburg.de/api/json"
_SLEEP      = 0.8


# ── Public API ────────────────────────────────────────────────────────────────

def extract_themes(
    conn: sqlite3.Connection,
    document_id: str,
    store=None,
) -> list[str]:
    """Extract themes for a document and write to SQLite.

    Returns a list of subject/theme strings.
    """
    themes: list[str] = []

    # 1. Wikidata main_subject — if QID known in knowledge graph
    if store is not None:
        wikidata_themes = _themes_from_wikidata(store, document_id)
        if wikidata_themes:
            themes = wikidata_themes

    # 2. RVK labels — from stored notations
    if not themes:
        rvk_themes = _themes_from_rvk_labels(conn, document_id)
        if rvk_themes:
            themes = rvk_themes

    # 3. Keywords → RVK API search
    if not themes:
        themes = _themes_from_rvk_search(conn, document_id)

    # 4. Fallback: multi-word keywords as themes
    if not themes:
        themes = _themes_from_keywords(conn, document_id)

    if themes:
        _write_themes(conn, document_id, themes)
        if store is not None:
            _write_theme_triples(store, document_id, themes)

    return themes


def themes_for_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Return stored themes, extracting if not yet present."""
    row = conn.execute(
        "SELECT subjects FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row and row["subjects"]:
        try:
            subjects = json.loads(row["subjects"])
            if isinstance(subjects, list) and subjects:
                return subjects
        except (json.JSONDecodeError, TypeError):
            pass
    return []


# ── Extraction methods ────────────────────────────────────────────────────────

def _themes_from_wikidata(store, document_id: str) -> list[str]:
    """Get main_subject labels from Wikidata for a document with known QID."""
    try:
        from atlas.knowledge.store import ATLAS_D
        doc_uri = ATLAS_D + document_id

        # Check if document has a Wikidata QID
        sparql = f"""
SELECT ?subject ?subjectLabel WHERE {{
  <{doc_uri}> <http://www.w3.org/2002/07/owl#sameAs> ?qid .
  FILTER(STRSTARTS(STR(?qid), "https://www.wikidata.org/entity/Q"))
  BIND(REPLACE(STR(?qid), "https://www.wikidata.org/entity/", "") AS ?qid_str)
}}
LIMIT 1
"""
        rows = store.query(sparql)
        if not rows:
            return []

        # We have a QID — fetch main_subject from Wikidata live
        qid_uri = str(list(store._store.quads_for_pattern(
            NamedNode(doc_uri),
            NamedNode("http://www.w3.org/2002/07/owl#sameAs"),
            None, None
        ))[0].object)
        qid = re.search(r'Q\d+', qid_uri)
        if not qid:
            return []

        return _wikidata_main_subjects(qid.group(0))

    except Exception as exc:
        log.debug("Wikidata theme extraction failed: %s", exc)
        return []


def _wikidata_main_subjects(qid: str) -> list[str]:
    """Fetch main_subject (P921) labels for a Wikidata item."""
    sparql = f"""
SELECT ?subjectLabel WHERE {{
  wd:{qid} wdt:P921 ?subject .
  ?subject rdfs:label ?subjectLabel .
  FILTER(LANG(?subjectLabel) IN ("en", "de"))
}}
LIMIT 10
"""
    url = ("https://query.wikidata.org/sparql?"
           + urllib.parse.urlencode({"query": sparql, "format": "json"}))
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": _USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        labels = [
            row["subjectLabel"]["value"]
            for row in data.get("results", {}).get("bindings", [])
            if row.get("subjectLabel", {}).get("value")
        ]
        # Deduplicate (prefer German labels when both exist)
        return list(dict.fromkeys(labels))[:8]
    except Exception as exc:
        log.debug("Wikidata main_subject query failed: %s", exc)
        return []


def _themes_from_rvk_labels(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Get human-readable RVK labels from stored notations."""
    rows = conn.execute(
        """
        SELECT identifier_value FROM document_identifiers
        WHERE document_id = ? AND identifier_type = 'rvk'
        """,
        (document_id,),
    ).fetchall()

    if not rows:
        return []

    labels = []
    for row in rows:
        notation = row["identifier_value"]
        label = _rvk_label_for_notation(notation)
        if label:
            labels.append(label)
        time.sleep(_SLEEP)

    return labels


def _themes_from_rvk_search(
    conn: sqlite3.Connection,
    document_id: str,
    max_themes: int = 3,
) -> list[str]:
    """Search RVK using document keywords and return top theme labels."""
    # Get stored keywords
    row = conn.execute(
        "SELECT keywords FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not row or not row["keywords"]:
        return []

    try:
        keywords = json.loads(row["keywords"])
    except (json.JSONDecodeError, TypeError):
        return []

    if not keywords:
        return []

    # Use the top 3 keywords as search query
    query = " ".join(keywords[:3])
    results = _rvk_search(query, max_results=max_themes)

    themes = []
    for r in results:
        label = r.get("benennung", "").strip()
        if label and len(label) > 4:
            themes.append(label)

    return themes


def _themes_from_keywords(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Use multi-word keywords directly as themes (offline fallback)."""
    row = conn.execute(
        "SELECT keywords FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not row or not row["keywords"]:
        return []

    try:
        keywords = json.loads(row["keywords"])
    except (json.JSONDecodeError, TypeError):
        return []

    # Only multi-word phrases make sense as themes
    return [kw for kw in keywords if len(kw.split()) >= 2][:5]


# ── RVK API helpers ───────────────────────────────────────────────────────────

def _rvk_search(query: str, max_results: int = 5) -> list[dict]:
    """Search RVK by keyword, return list of {notation, benennung} dicts."""
    url = f"{_RVK_API}/search/{urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", {}).get("result", [])
        return [
            {"notation": r.get("notation", ""), "benennung": r.get("benennung", "")}
            for r in results[:max_results]
            if r.get("notation")
        ]
    except Exception as exc:
        log.debug("RVK search failed for %r: %s", query, exc)
        return []


def _rvk_label_for_notation(notation: str) -> str | None:
    """Fetch the German label for an RVK notation."""
    notation_enc = urllib.parse.quote(notation.strip().replace(" ", "%20"))
    url = f"{_RVK_API}/node/{notation_enc}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("node", {}).get("benennung")
    except Exception as exc:
        log.debug("RVK label lookup failed for %r: %s", notation, exc)
        return None


# ── Database and graph writes ─────────────────────────────────────────────────

def _write_themes(
    conn: sqlite3.Connection,
    document_id: str,
    themes: list[str],
) -> None:
    """Write themes to documents.subjects column."""
    try:
        conn.execute(
            "UPDATE documents SET subjects = ? WHERE document_id = ?",
            (json.dumps(themes, ensure_ascii=False), document_id),
        )
        conn.commit()
    except Exception as exc:
        # subjects column may not exist yet (needs migration 0013)
        log.debug("Could not write subjects (run atlas dev db migrate): %s", exc)


def _write_theme_triples(
    store,
    document_id: str,
    themes: list[str],
) -> None:
    """Write atlas:about triples to the knowledge graph."""
    try:
        from atlas.knowledge.store import P, doc_uri, KnowledgeStore, _slugify
        doc    = doc_uri(document_id)
        triples = []
        about_pred = NamedNode("https://atlas.local/ontology#about")
        for theme in themes:
            theme_node = NamedNode("https://atlas.local/theme/" + _slugify(theme))
            triples.append((doc, about_pred, theme_node))
            triples.append((theme_node, P["label"], KnowledgeStore.lit(theme)))
        store.add_doc_triples(document_id, triples)
    except Exception as exc:
        log.debug("Theme triple write failed: %s", exc)
