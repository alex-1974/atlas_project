# src/atlas/enrich/gnd.py
"""GND (Gemeinsame Normdatei) enrichment and GND→RVK classification pipeline.

Two functions:

1. enrich_document(conn, document_id) → list[str]
   Finds GND entities matching the document's keywords via lobid.org API.
   Stores GND identifiers in document_identifiers (type='gnd').

2. rvk_via_gnd(conn, document_id) → list[str]
   Full pipeline: Keywords → GND preferred labels → RVK nodes search.
   Returns RVK notations ranked by match quality.
   Called by atlas enrich --rvk when direct keyword→RVK fails.

Why GND as intermediate step
-----------------------------
GND provides controlled vocabulary labels (e.g. 'Niederdeutsches Hallenhaus'
instead of YAKE's 'Niederdeutsche Hallenhaus') that match RVK node names
more reliably. The lobid.org search is also fuzzy — it handles partial
matches and variant spellings.

API
---
lobid.org GND search: https://lobid.org/gnd/search
No authentication. Rate limit: ~1 req/sec polite.
Documentation: https://lobid.org/gnd/api
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_LOBID_API  = "https://lobid.org/gnd/search"
_USER_AGENT = "Atlas/2.0 (atlas-catalog) Python"
_SLEEP      = 0.3


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_document(
    conn: sqlite3.Connection,
    document_id: str,
    store=None,
) -> list[str]:
    """Find GND entities for a document's keywords and store them.

    Returns list of GND identifier strings (e.g. ['4375536-7', ...]).
    """
    keywords = _get_keywords(conn, document_id)
    if not keywords:
        return []

    gnd_hits: list[dict] = []
    for kw in keywords[:5]:
        hits = _lobid_search(kw, max_results=2)
        gnd_hits.extend(hits)
        time.sleep(_SLEEP)
        if len(gnd_hits) >= 6:
            break

    # Deduplicate by GND identifier
    seen: set[str] = set()
    unique: list[dict] = []
    for hit in gnd_hits:
        gid = hit.get("gnd_id", "")
        if gid and gid not in seen:
            seen.add(gid)
            unique.append(hit)

    if unique:
        _write_gnd_identifiers(conn, document_id, unique)
        if store is not None:
            _write_gnd_triples(store, document_id, unique)

    return [h["gnd_id"] for h in unique]


def rvk_via_gnd(
    conn: sqlite3.Connection,
    document_id: str,
    max_results: int = 3,
) -> list[str]:
    """Find RVK notations via GND preferred labels.

    Pipeline:
        1. Get document keywords
        2. Search lobid.org for GND entities
        3. Use GND preferred labels as RVK search queries
        4. Return top RVK notations ranked by match count

    Returns list of RVK notation strings.
    """
    from atlas.enrich.rvk import search_notation

    keywords = _get_keywords(conn, document_id)
    if not keywords:
        return []

    # Step 1: Collect GND preferred labels
    gnd_labels: list[str] = []
    for kw in keywords[:5]:
        hits = _lobid_search(kw, max_results=2)
        for hit in hits:
            label = hit.get("preferred_name", "")
            if label and label not in gnd_labels:
                gnd_labels.append(label)
        time.sleep(_SLEEP)

    if not gnd_labels:
        return []

    # Step 2: Search RVK using GND preferred labels
    # Try individual words from labels (RVK nodes search works best with
    # single content words)
    rvk_scores: dict[str, int] = {}
    rvk_labels: dict[str, str] = {}

    for label in gnd_labels[:6]:
        words = [w for w in label.split() if len(w) >= 5]
        for word in words[:2]:
            hits = search_notation(word, max_results=3)
            time.sleep(_SLEEP)
            for hit in hits:
                notation = hit.get("notation", "")
                lbl      = hit.get("label", "")
                if notation:
                    rvk_scores[notation] = rvk_scores.get(notation, 0) + 1
                    rvk_labels[notation] = lbl

    if not rvk_scores:
        return []

    # Return top notations by score
    ranked = sorted(rvk_scores.items(), key=lambda x: -x[1])
    return [notation for notation, _ in ranked[:max_results]]


def preferred_labels_for_keywords(keywords: list[str]) -> list[str]:
    """Return GND preferred labels for a list of keywords.

    Used by themes.py as a controlled-vocabulary normalisation step.
    """
    labels: list[str] = []
    for kw in keywords[:6]:
        hits = _lobid_search(kw, max_results=1)
        if hits:
            label = hits[0].get("preferred_name", "")
            if label and label not in labels:
                labels.append(label)
        time.sleep(_SLEEP)
    return labels


# ── Section enrichment ───────────────────────────────────────────────────────

def enrich_sections(
    section_keywords: dict,
    language: str = "en",
    max_level: int = 3,
) -> dict[int | None, list[dict]]:
    """
    GND-Lookup für Section-Keywords aus atlas.semantic.keywords.

    Args:
        section_keywords: {node_id: SectionKeywords} aus semantic.keywords
        language:         Dokument-Sprache für Normalisierung

    Returns:
        {node_id: [{"gnd_id": str, "preferred_name": str, "keyword": str}]}
    """
    results: dict = {}

    for node_id, sk in section_keywords.items():
        hits_for_section: list[dict] = []
        seen_gnd: set[str] = set()

        for kw in sk.keywords[:3]:  # max 3 pro Abschnitt
            # Varianten für GND-Lookup (Original + normalisiert für DE)
            variants = _kw_variants(kw, sk.language)
            for variant in variants:
                hits = _lobid_search(variant, max_results=2)
                time.sleep(_SLEEP)
                for h in hits:
                    gid = h.get("gnd_id", "")
                    if gid and gid not in seen_gnd:
                        seen_gnd.add(gid)
                        hits_for_section.append({**h, "keyword": kw})
                if hits_for_section:
                    break  # Erste erfolgreiche Variante reicht

        results[node_id] = hits_for_section

    return results


def _kw_variants(kw: str, language: str) -> list[str]:
    """
    Gibt Lookup-Varianten eines Keywords zurück.
    Nutzt simplemma für Lemmatisierung (Original + Lemma).
    """
    try:
        from atlas.semantic.lemma import lemmatize_keywords
        return lemmatize_keywords([kw], lang=language)
    except Exception:
        return [kw]


# ── lobid.org API ─────────────────────────────────────────────────────────────

def _lobid_search(
    query: str,
    max_results: int = 3,
) -> list[dict]:
    """Search lobid.org GND for subject heading entities matching a keyword.

    Restricted to SubjectHeading, PlaceOrGeographicName, BuildingOrMemorial
    to avoid matching persons, works, or corporate bodies which would
    produce irrelevant RVK notations.

    Returns list of {"gnd_id": str, "preferred_name": str, "type": list}.
    """
    # Filter to subject-like entity types only
    type_filter = (
        "type:SubjectHeading OR type:PlaceOrGeographicName "
        "OR type:BuildingOrMemorial OR type:EthnographicName"
    )
    params = urllib.parse.urlencode({
        "q":      f"{query} AND ({type_filter})",
        "format": "json",
        "size":   max_results,
    })
    url = f"{_LOBID_API}?{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for item in data.get("member", [])[:max_results]:
            gnd_id = item.get("gndIdentifier", "")
            label  = item.get("preferredName", "")
            types  = item.get("type", [])
            if gnd_id and label:
                results.append({
                    "gnd_id":         gnd_id,
                    "preferred_name": label,
                    "type":           types,
                })
        # Relevanzfilter: mindestens ein substantielles Wort (>4 Zeichen)
        # muss zwischen Suchterm und GND preferred_name übereinstimmen.
        # Verhindert Zufallstreffer wie "des Jahres" → "Wildlife-Fotografien"
        query_words = {w.lower() for w in query.split() if len(w) > 4}
        filtered = []
        for r in results:
            name_words = {w.lower() for w in r["preferred_name"].split()}
            if query_words & name_words:
                filtered.append(r)
        return filtered

    except Exception as exc:
        log.debug("lobid GND search failed for %r: %s", query, exc)
        return []


# ── Database helpers ──────────────────────────────────────────────────────────

def _get_keywords(conn: sqlite3.Connection, document_id: str) -> list[str]:
    row = conn.execute(
        "SELECT keywords FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not row or not row["keywords"]:
        return []
    try:
        return json.loads(row["keywords"])
    except (json.JSONDecodeError, TypeError):
        return []


def _write_gnd_identifiers(
    conn: sqlite3.Connection,
    document_id: str,
    hits: list[dict],
) -> None:
    for hit in hits:
        gnd_id = hit.get("gnd_id", "")
        if gnd_id:
            conn.execute(
                """
                INSERT INTO document_identifiers
                    (document_id, identifier_type, identifier_value)
                VALUES (?, 'gnd', ?)
                ON CONFLICT DO NOTHING
                """,
                (document_id, gnd_id),
            )
    conn.commit()


def _write_gnd_triples(store, document_id: str, hits: list[dict]) -> None:
    """Write atlas:has_gnd_keyword triples."""
    try:
        from atlas.knowledge.store import P, doc_uri, KnowledgeStore
        from pyoxigraph import NamedNode
        doc   = doc_uri(document_id)
        pred  = NamedNode("https://atlas.local/ontology#has_gnd_keyword")
        triples = []
        for hit in hits:
            gnd_id = hit.get("gnd_id", "")
            label  = hit.get("preferred_name", "")
            if gnd_id:
                gnd_node = NamedNode(f"https://d-nb.info/gnd/{gnd_id}")
                triples.append((doc, pred, gnd_node))
                if label:
                    triples.append((gnd_node, P["label"], KnowledgeStore.lit(label)))
        store.add_doc_triples(document_id, triples)
    except Exception as exc:
        log.debug("GND triple write failed: %s", exc)
