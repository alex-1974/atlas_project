"""
atlas.enrich.concept

Konzept-Normalisierung via Wikidata.

Ein Wikidata-Lookup pro Keyword liefert:
  - QID als stabiler, mehrsprachiger Identifier
  - Labels in EN/DE/FR
  - Externe Identifier: GND (P227), LCSH (P244), Getty AAT (P1014), RAMEAU (P1349)

Öffentliche API:
    hit  = lookup_concept("Fachwerkbau", lang="de")
    hits = lookup_concepts(["timber framing", "farmstead"], lang="en")
    topic = best_topic(hits, doc_lang="en")
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.wikidata.org/w/api.php"
_SPARQL_URL = "https://query.wikidata.org/sparql"
_UA         = "Atlas/2.0 (atlas-catalog; mailto:atlas@local)"
_SLEEP      = 0.4

# Wikidata Properties die wir holen
_PROPS = {
    "gnd":       "P227",
    "lcsh":      "P244",
    "getty_aat": "P1014",
    "rameau":    "P1349",
}

# Entity-Typen die wir NICHT als Konzepte wollen
# (spezifische Gebäude, Gemälde, Bücher, Personen, etc.)
_EXCLUDE_TYPES = {
    "Q5",          # Mensch
    "Q43229",      # Organisation
    "Q35127",      # Website
    "Q571",        # Buch
    "Q3305213",    # Gemälde
    "Q811979",     # architektonisches Bauwerk (spezifisch)
    "Q41176",      # Gebäude (spezifisch)
}


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class ConceptHit:
    """Ein normalisiertes Konzept aus Wikidata."""
    qid:       str
    keyword:   str                        # ursprüngliches YAKE-Keyword
    labels:    dict[str, str] = field(default_factory=dict)  # lang → label
    identifiers: dict[str, str] = field(default_factory=dict)  # gnd/lcsh/...
    description: str = ""

    def label(self, lang: str = "en") -> str:
        """Label in gewünschter Sprache, Fallback auf EN."""
        return (self.labels.get(lang)
                or self.labels.get("en")
                or self.qid)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def lookup_concept(
    keyword: str,
    lang: str = "en",
) -> ConceptHit | None:
    """
    Sucht ein Wikidata-Konzept für ein Keyword.

    Schritt 1: wbsearchentities → QID
    Schritt 2: SPARQL → Labels + externe Identifier

    Returns ConceptHit oder None wenn kein passendes Konzept gefunden.
    """
    qid = _search_qid(keyword, lang=lang)
    if not qid:
        return None
    time.sleep(_SLEEP)

    ids = _fetch_identifiers(qid)
    if not ids:
        return None

    return ConceptHit(
        qid=qid,
        keyword=keyword,
        labels={
            "en": ids.get("label_en", ""),
            "de": ids.get("label_de", ""),
            "fr": ids.get("label_fr", ""),
            "nl": ids.get("label_nl", ""),
        },
        identifiers={
            k: ids[k] for k in _PROPS if k in ids
        },
        description=ids.get("description_en", ""),
    )


def lookup_concepts(
    keywords: list[str],
    lang: str = "en",
    max_keywords: int = 6,
) -> list[ConceptHit]:
    """
    Sucht Konzepte für mehrere Keywords.
    Dedupliziert nach QID — jedes Konzept nur einmal.

    Args:
        keywords:     Liste von YAKE-Keywords
        lang:         Dokument-Sprache
        max_keywords: Maximale Anzahl Lookups

    Returns:
        Liste von ConceptHits (dedupliziert nach QID)
    """
    seen_qids: set[str] = set()
    results: list[ConceptHit] = []

    for kw in keywords[:max_keywords]:
        hit = lookup_concept(kw, lang=lang)
        time.sleep(_SLEEP)
        if hit and hit.qid not in seen_qids:
            seen_qids.add(hit.qid)
            results.append(hit)

    return results


def best_topic(
    hits: list[ConceptHit],
    doc_lang: str = "en",
) -> ConceptHit | None:
    """
    Wählt das beste Konzept als Dokument-Topic.

    Strategie:
      1. Konzepte mit externen Identifiern bevorzugen (GND, LCSH, Getty AAT)
      2. Konzepte mit Label in der Dokumentsprache bevorzugen
      3. Erstes Konzept als Fallback

    Returns:
        Bestes ConceptHit oder None
    """
    if not hits:
        return None

    def score(h: ConceptHit) -> int:
        s = 0
        s += len(h.identifiers) * 2   # externe IDs = Qualitätssignal
        if h.labels.get(doc_lang):
            s += 3                     # Label in Dokumentsprache
        if h.labels.get("en"):
            s += 1
        return s

    return max(hits, key=score)


# ---------------------------------------------------------------------------
# Persistenz
# ---------------------------------------------------------------------------

def save_concepts(
    conn,
    document_id: str,
    hits: list[ConceptHit],
) -> int:
    """
    Schreibt Konzepte in document_identifiers.

    Identifier-Typen: wikidata, gnd, lcsh, getty_aat, rameau

    Returns:
        Anzahl neu geschriebener Einträge
    """
    written = 0
    for hit in hits:
        # Wikidata QID
        try:
            conn.execute(
                """INSERT INTO document_identifiers
                   (document_id, identifier_type, identifier_value)
                   VALUES (?, 'wikidata', ?)
                   ON CONFLICT DO NOTHING""",
                (document_id, hit.qid),
            )
            written += 1
        except Exception:
            pass

        # Externe Identifier
        for id_type, id_value in hit.identifiers.items():
            if id_value:
                try:
                    conn.execute(
                        """INSERT INTO document_identifiers
                           (document_id, identifier_type, identifier_value)
                           VALUES (?, ?, ?)
                           ON CONFLICT DO NOTHING""",
                        (document_id, id_type, id_value),
                    )
                    written += 1
                except Exception:
                    pass

    conn.commit()
    return written


def save_topic(
    conn,
    document_id: str,
    topic: ConceptHit,
    doc_lang: str = "en",
    force: bool = False,
) -> None:
    """Schreibt Topic-Label und QID in documents."""
    if not force:
        row = conn.execute(
            "SELECT topic FROM documents WHERE document_id=?",
            (document_id,)
        ).fetchone()
        if row and row[0]:
            return

    label = topic.label(doc_lang)
    # topic_qid Spalte optional — nur schreiben wenn vorhanden
    try:
        conn.execute(
            "UPDATE documents SET topic=?, updated_at=datetime('now') "
            "WHERE document_id=?",
            (label, document_id),
        )
    except Exception:
        conn.execute(
            "UPDATE documents SET topic=? WHERE document_id=?",
            (label, document_id),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _search_qid(term: str, lang: str = "en") -> str | None:
    """wbsearchentities → QID."""
    params = urllib.parse.urlencode({
        "action":   "wbsearchentities",
        "search":   term,
        "language": lang,
        "type":     "item",
        "limit":    3,
        "format":   "json",
        "uselang":  lang,
    })
    try:
        req = urllib.request.Request(
            f"{_SEARCH_URL}?{params}",
            headers={"User-Agent": _UA},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        hits = data.get("search", [])
        if not hits:
            return None
        # Ersten Treffer nehmen (wbsearch sortiert nach Relevanz)
        return hits[0]["id"]
    except Exception as exc:
        logger.debug("wikidata search failed for %r: %s", term, exc)
        return None


def _fetch_identifiers(qid: str) -> dict:
    """SPARQL → Labels + externe Identifier."""
    prop_clauses = "\n  ".join(
        f"OPTIONAL {{ wd:{qid} wdt:{prop} ?{name}. }}"
        for name, prop in _PROPS.items()
    )
    sparql = f"""
SELECT ?label_en ?label_de ?label_fr ?label_nl ?description_en
       ?gnd ?lcsh ?getty_aat ?rameau
WHERE {{
  OPTIONAL {{ wd:{qid} rdfs:label ?label_en.
              FILTER(LANG(?label_en)="en") }}
  OPTIONAL {{ wd:{qid} rdfs:label ?label_de.
              FILTER(LANG(?label_de)="de") }}
  OPTIONAL {{ wd:{qid} rdfs:label ?label_fr.
              FILTER(LANG(?label_fr)="fr") }}
  OPTIONAL {{ wd:{qid} rdfs:label ?label_nl.
              FILTER(LANG(?label_nl)="nl") }}
  OPTIONAL {{ wd:{qid} schema:description ?description_en.
              FILTER(LANG(?description_en)="en") }}
  OPTIONAL {{ wd:{qid} wdt:P227  ?gnd. }}
  OPTIONAL {{ wd:{qid} wdt:P244  ?lcsh. }}
  OPTIONAL {{ wd:{qid} wdt:P1014 ?getty_aat. }}
  OPTIONAL {{ wd:{qid} wdt:P1349 ?rameau. }}
}} LIMIT 1
"""
    params = urllib.parse.urlencode({"query": sparql, "format": "json"})
    try:
        req = urllib.request.Request(
            f"{_SPARQL_URL}?{params}",
            headers={"User-Agent": _UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return {}
        row = bindings[0]
        return {k: row[k]["value"] for k in row if row[k]["value"] != "—"}
    except Exception as exc:
        logger.debug("wikidata sparql failed for %s: %s", qid, exc)
        return {}
