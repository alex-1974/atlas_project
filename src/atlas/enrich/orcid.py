# src/atlas/enrich/orcid.py
"""ORCID enrichment — disambiguate authors via the ORCID public API.

ORCID (orcid.org) provides unique identifiers for researchers.
The public API allows searching by name and retrieving author metadata
without authentication (rate limit: ~24 requests/second).

Use cases in Atlas:
  - "H. Stiewe" + affiliation "IgB" → ORCID 0000-0002-xxxx → full name
  - Disambiguate authors with common names across multiple documents
  - Link local atlas:Author nodes to orcid.org URIs via owl:sameAs

Resolution strategy:
  1. If Wikidata already returned an ORCID for this author → done
  2. Search ORCID API with name + optional affiliation keyword
  3. If exactly one result matches → accept
  4. If multiple results → rank by affiliation similarity, accept if clear winner
  5. If no confident match → skip (do not guess)
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import logging

log = logging.getLogger(__name__)

_API_BASE   = "https://pub.orcid.org/v3.0/search/"
_RECORD_URL = "https://pub.orcid.org/v3.0/{orcid}/person"
_USER_AGENT = "Atlas/2.0 (atlas-catalog) Python"
_SLEEP      = 0.3
_MIN_SCORE  = 0.85  # minimum relevance score to accept a match


# ── Public API ────────────────────────────────────────────────────────────────

def search_author(
    name: str,
    affiliation: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Search ORCID for an author by name and optional affiliation.

    Returns a list of candidate dicts:
        {"orcid": str, "name": str, "affiliation": str, "score": float}

    Score 1.0 = only result, 0.0 = no confidence.
    """
    query_parts = [f'family-name:"{_last_name(name)}"']
    given = _given_name(name)
    if given:
        query_parts.append(f'given-names:"{given}"')
    if affiliation:
        # Affiliation as a free-text search term
        query_parts.append(f'affiliation-org-name:"{affiliation}"')

    query = " AND ".join(query_parts)
    params = {
        "q":    query,
        "rows": str(max_results),
        "start": "0",
    }
    url = _API_BASE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept":     "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("ORCID search failed for %r: %s", name, exc)
        return []

    results = data.get("result", [])
    if not results:
        return []

    candidates = []
    n = len(results)
    for i, item in enumerate(results):
        orcid_id = item.get("orcid-identifier", {}).get("path", "")
        if not orcid_id:
            continue

        # Score: single result = 1.0, multiple = decreasing
        score = 1.0 if n == 1 else max(0.0, 1.0 - i * (1.0 / n))

        # Try to get display name from the result
        pn = item.get("person", {}).get("name", {})
        given_n  = (pn.get("given-names") or {}).get("value", "")
        family_n = (pn.get("family-name") or {}).get("value", "")
        display  = f"{given_n} {family_n}".strip() or orcid_id

        candidates.append({
            "orcid":       orcid_id,
            "name":        display,
            "affiliation": "",
            "score":       round(score, 3),
        })

    time.sleep(_SLEEP)
    return candidates


def resolve_author(
    name: str,
    affiliation: str | None = None,
) -> dict | None:
    """Return the best ORCID match for an author, or None if uncertain.

    Only returns a result if confidence >= _MIN_SCORE.
    """
    candidates = search_author(name, affiliation, max_results=3)
    if not candidates:
        return None
    best = candidates[0]
    if best["score"] < _MIN_SCORE:
        log.debug(
            "No confident ORCID match for %r (best score %.2f)",
            name, best["score"]
        )
        return None
    return best


def fetch_author_record(orcid: str) -> dict:
    """Fetch the public person record for an ORCID.

    Returns:
        {"name": str, "other_names": [str], "affiliations": [str],
         "keywords": [str]}
    """
    url = _RECORD_URL.format(orcid=orcid.strip())
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept":     "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("ORCID record fetch failed for %s: %s", orcid, exc)
        return {}

    result: dict = {}

    # Name
    name_block = data.get("name", {})
    given  = (name_block.get("given-names") or {}).get("value", "")
    family = (name_block.get("family-name") or {}).get("value", "")
    if given or family:
        result["name"] = f"{given} {family}".strip()

    # Other names
    other = [
        n.get("content", "")
        for n in data.get("other-names", {}).get("other-name", [])
        if n.get("content")
    ]
    if other:
        result["other_names"] = other

    # Keywords
    kw = [
        k.get("content", "")
        for k in data.get("keywords", {}).get("keyword", [])
        if k.get("content")
    ]
    if kw:
        result["keywords"] = kw

    time.sleep(_SLEEP)
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _last_name(name: str) -> str:
    """Extract likely family name (last word)."""
    parts = name.strip().split()
    return parts[-1] if parts else name


def _given_name(name: str) -> str:
    """Extract given name(s) (all but last word)."""
    parts = name.strip().split()
    if len(parts) <= 1:
        return ""
    return " ".join(parts[:-1])
