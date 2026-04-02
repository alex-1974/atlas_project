# src/atlas/enrich/topic.py
"""Topic extraction — semantically normalized concept per document.

Topic vs. extractive summary
-----------------------------
A topic is not a sentence extracted from the document — it is the
dominant semantic concept, normalized against a controlled vocabulary.

'Niederdeutsches Hallenhaus' (GND preferred label) is better than
'Das Niederdeutsche Hallenhaus ist Bauernhaus des Jahres 2023' as a
topic because it is:
  - concise (a concept, not a sentence)
  - controlled (matches GND / RVK / library headings)
  - searchable (other systems use the same label)

Pipeline
--------
1. Collect candidates from title + YAKE keywords (already stored)
2. Look up GND preferred labels for stored GND identifiers
3. Score each candidate:
     +3 if found in document title
     +2 if found in stored keywords
     +1 for each GND entity of type SubjectHeading
     +1 for PlaceOrGeographicName / BuildingOrMemorial
      0 for Persons, CorporateBodies (filtered out)
4. Top-1 preferred label → documents.topic

Fallback chain (no network / no GND data):
    YAKE keyword that appears in title → first YAKE keyword → title

Stored in:
    documents.topic (TEXT)
    Oxigraph: atlas:topic triple (optional)
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import urllib.request

log = logging.getLogger(__name__)

_LOBID_API  = "https://lobid.org/gnd"
_USER_AGENT = "Atlas/2.0 (atlas-catalog) Python"
_SLEEP      = 0.5

# GND types that represent subject concepts (not persons or organisations)
_SUBJECT_TYPES = {
    "SubjectHeading",
    "SubjectHeadingSensoStricto",
    "PlaceOrGeographicName",
    "BuildingOrMemorial",
    "EthnographicName",
    "NaturalGeographicUnit",
}


# ── Public API ────────────────────────────────────────────────────────────────

def extract_topic(
    conn: sqlite3.Connection,
    document_id: str,
    store=None,
    force: bool = False,
) -> str | None:
    """Extract and store the dominant topic for a document.

    Returns the topic string, or None if extraction failed.
    """
    if not force:
        row = conn.execute(
            "SELECT topic FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row and row["topic"]:
            return row["topic"]

    topic = (
        _topic_via_gnd(conn, document_id)
        or _topic_from_keywords(conn, document_id)
        or _topic_from_title(conn, document_id)
    )

    if topic:
        _write_topic(conn, document_id, topic)
        if store is not None:
            _write_topic_triple(store, document_id, topic)

    return topic


def topic_for_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Return stored topic, extracting if not yet present."""
    row = conn.execute(
        "SELECT topic FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row and row["topic"]:
        return row["topic"]
    return extract_topic(conn, document_id)


# ── GND-based topic extraction ────────────────────────────────────────────────

def _topic_via_gnd(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Find the dominant topic using stored GND identifiers.

    Looks up preferred labels via lobid.org and scores them against
    the document title and keywords.
    """
    gnd_ids = _get_gnd_ids(conn, document_id)
    if not gnd_ids:
        return None

    title    = _get_title(conn, document_id)
    keywords = _get_keywords(conn, document_id)

    title_lower    = title.lower() if title else ""
    keyword_lowers = {kw.lower() for kw in keywords}

    scored: list[tuple[float, str]] = []

    for gnd_id in gnd_ids[:10]:
        entity = _lobid_fetch(gnd_id)
        if not entity:
            continue
        time.sleep(_SLEEP)

        types  = set(entity.get("type", []))
        label  = entity.get("label", "").strip()

        if not label:
            continue

        # Only subject concepts — skip persons and corporate bodies
        if not (types & _SUBJECT_TYPES):
            continue

        score = 1.0

        # Strong signal: label appears in title
        label_lower = label.lower()
        if label_lower in title_lower:
            score += 3.0
        elif any(word in title_lower for word in label_lower.split()
                 if len(word) >= 5):
            score += 1.0

        # Medium signal: label appears in keywords
        if label_lower in keyword_lowers:
            score += 2.0
        elif any(label_lower in kw.lower() or kw.lower() in label_lower
                 for kw in keywords):
            score += 1.0

        # Prefer SubjectHeading over geographic names
        if "SubjectHeading" in types or "SubjectHeadingSensoStricto" in types:
            score += 1.0
        elif "PlaceOrGeographicName" in types or "BuildingOrMemorial" in types:
            # Geographic entities only qualify if they have a strong title match
            if label_lower not in title_lower:
                continue  # skip geographic entities without title match

        scored.append((score, label))

    if not scored:
        return None

    # Return highest-scored label
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def _lobid_fetch(gnd_id: str) -> dict | None:
    """Fetch GND entity data from lobid.org."""
    url = f"{_LOBID_API}/{gnd_id}.json"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "label": data.get("preferredName", ""),
            "type":  data.get("type", []),
        }
    except Exception as exc:
        log.debug("lobid fetch failed for %r: %s", gnd_id, exc)
        return None


# ── Fallback methods ──────────────────────────────────────────────────────────

def _topic_from_keywords(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Use the best YAKE keyword as topic fallback.

    Prefers keywords that also appear in the title.
    """
    keywords = _get_keywords(conn, document_id)
    title    = (_get_title(conn, document_id) or "").lower()

    if not keywords:
        return None

    # Prefer multi-word keywords that appear in title
    for kw in keywords:
        if len(kw.split()) >= 2 and kw.lower() in title:
            return kw

    # First multi-word keyword
    for kw in keywords:
        if len(kw.split()) >= 2:
            return kw

    return keywords[0] if keywords else None


def _topic_from_title(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Last resort: use the document title."""
    title = _get_title(conn, document_id)
    if title:
        # Strip subtitle after colon if very long
        if len(title) > 80 and ":" in title:
            title = title.split(":")[0].strip()
        return title
    return None


# ── Database helpers ──────────────────────────────────────────────────────────

def _get_gnd_ids(conn: sqlite3.Connection, document_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT identifier_value FROM document_identifiers "
        "WHERE document_id = ? AND identifier_type = 'gnd'",
        (document_id,),
    ).fetchall()
    return [r["identifier_value"] for r in rows]


def _get_title(conn: sqlite3.Connection, document_id: str) -> str | None:
    row = conn.execute(
        "SELECT title FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    return row["title"] if row else None


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


def _write_topic(
    conn: sqlite3.Connection,
    document_id: str,
    topic: str,
) -> None:
    try:
        conn.execute(
            "UPDATE documents SET topic = ? WHERE document_id = ?",
            (topic, document_id),
        )
        conn.commit()
    except Exception as exc:
        log.debug("Could not write topic: %s", exc)


def _write_topic_triple(store, document_id: str, topic: str) -> None:
    """Write atlas:topic triple to the knowledge graph."""
    try:
        from atlas.knowledge.store import P, doc_uri, KnowledgeStore
        from pyoxigraph import NamedNode
        doc  = doc_uri(document_id)
        pred = NamedNode("https://atlas.local/ontology#topic")
        store.add_doc_triples(document_id, [
            (doc, pred, KnowledgeStore.lit(topic))
        ])
    except Exception as exc:
        log.debug("Topic triple write failed: %s", exc)
