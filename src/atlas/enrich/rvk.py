# src/atlas/enrich/rvk.py
"""RVK (Regensburger Verbundklassifikation) enrichment.

The RVK is the most widely used library classification system in
German-speaking countries.  It assigns hierarchical notations like
`ZH 5500` (Historische Gebäude und Denkmäler) to subject areas.

Two-step approach
-----------------
1. **Local detection** — scan the document for RVK notations already
   present in the text (e.g. in a library catalog entry or header).
   Pattern: 2-3 uppercase letters + space + 3-5 digits, optionally
   followed by a space and more digits: `ZH 5500`, `AN 96200`.

2. **API lookup** — if no local notation is found, query the RVK SPARQL
   endpoint (rvk.uni-regensburg.de) using the document's title and
   subject keywords to find the best-matching notation.

Output
------
- SQLite: `document_identifiers` table (type="rvk")
- Oxigraph: `atlas:has_rvk_class` triples

RVK API
-------
Endpoint: https://rvk.uni-regensburg.de/api/json/descendants/<notation>
SPARQL:   https://rvk.uni-regensburg.de/sparql
No authentication required.  Polite use: 1 request/second.
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

_RVK_API  = "https://rvk.uni-regensburg.de/api/json"
_RVK_SPARQL = "https://rvk.uni-regensburg.de/sparql"
_USER_AGENT = "Atlas/2.0 (atlas-catalog) Python"
_SLEEP = 1.0

# RVK notation pattern: 2-3 letters + space + 3-5 digits
_RVK_NOTATION_RE = re.compile(
    r'\b([A-Z]{2,3})\s+(\d{3,5})(?:\s+\d{3,5})?\b'
)

# Valid RVK top-level subject group letters (2-letter prefixes).
# Source: https://rvk.uni-regensburg.de/regensburger-verbundklassifikation-online
# This whitelist prevents false positives like "NJ 07030" (US zip code),
# "AT 100" (Austrian standard), "IN 5000" (Indian rupee notation), etc.
_RVK_VALID_PREFIXES: set[str] = {
    # A  Allgemeines
    "AN", "AP", "AR", "AS", "AX",
    # B  Theologie und Religionswissenschaft
    "BC", "BD", "BE", "BG", "BH", "BK", "BL", "BN", "BP", "BR", "BS", "BT", "BV",
    # C  Philosophie
    "CA", "CB", "CC", "CD", "CE", "CF", "CI", "CK",
    # D  Pädagogik
    "DB", "DC", "DD", "DE", "DF", "DG", "DH", "DI", "DK", "DL", "DM", "DN", "DP",
    # E  Allgemeine und vergleichende Sprach- und Literaturwissenschaft
    "EB", "EC", "ED", "EE", "EF", "EG", "EH", "EI", "EK", "EL", "EM", "EN",
    # F  Englische Sprach- und Literaturwissenschaft
    "FA", "FB", "FC", "FD", "FE", "FF", "FH", "FK", "FL", "FM", "FN", "FP",
    # G  Germanistik, Niederlandistik, Skandinavistik
    "GA", "GB", "GC", "GD", "GE", "GF", "GG", "GH", "GI", "GK", "GL", "GM",
    "GN", "GP", "GQ", "GR", "GS", "GT", "GU",
    # H  Griechische und lateinische Sprach- und Literaturwissenschaft
    "HA", "HB", "HC", "HD", "HE", "HF", "HG", "HH", "HI", "HK",
    # I  Romanische Sprach- und Literaturwissenschaft
    "IA", "IB", "IC", "ID", "IE", "IF", "IH", "IK", "IL", "IM",
    # K  Slawische und baltische Philologie
    "KA", "KB", "KC", "KD", "KE", "KF", "KG", "KH", "KI", "KK",
    # L  Archäologie
    "LA", "LB", "LC", "LD", "LE", "LF", "LG", "LH",
    # M  Geographie, Heimat- und Länderkunde, Reisen, Atlanten
    "MA", "MB", "MC", "MD", "ME", "MF", "MG", "MH", "MI", "MK", "ML", "MM",
    "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW", "MX", "MY",
    # N  Geschichte
    "NA", "NB", "NC", "ND", "NE", "NF", "NG", "NH", "NI", "NK", "NL", "NM",
    "NN", "NO", "NP", "NQ", "NR", "NS", "NT", "NU", "NW", "NX", "NY",
    # P  Sozialwissenschaften
    "PA", "PB", "PC", "PD", "PE", "PF", "PG", "PH", "PI", "PK", "PL", "PM",
    "PN", "PP", "PQ", "PR", "PS", "PT", "PU", "PV", "PW", "PX", "PY",
    # Q  Wirtschaftswissenschaften
    "QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH", "QI", "QK", "QL", "QM",
    "QN", "QP", "QQ", "QR", "QS", "QT", "QU", "QV", "QW", "QX", "QY",
    # R  Rechtswissenschaft
    "RA", "RB", "RC", "RD", "RE", "RF", "RG", "RH", "RI", "RK", "RL", "RM",
    "RN", "RP", "RQ", "RR", "RS", "RT", "RU", "RV", "RW", "RX", "RY",
    # S  Medizin
    "SA", "SB", "SC", "SD", "SE", "SF", "SG", "SH", "SI", "SK", "SL", "SM",
    "SN", "SP", "SQ", "SR", "SS", "ST", "SU", "SV", "SW", "SX", "SY",
    # T  Technik, Ingenieurwissenschaft
    "TA", "TB", "TC", "TD", "TE", "TF", "TG", "TH", "TI", "TK", "TL", "TM",
    "TN", "TP", "TQ", "TR", "TS", "TT", "TU", "TV", "TW", "TX", "TY",
    # U  Militärwissenschaft
    "UB", "UC", "UD", "UE", "UF",
    # V  Verkehr, Transport, Kommunikation
    "VA", "VB", "VC", "VD", "VE", "VF", "VG", "VH", "VI", "VK",
    # W  Sport und Spiele
    "WA", "WB", "WC", "WD", "WE", "WF", "WG", "WH", "WI", "WK",
    # X  Kunst, Kunstgeschichte
    "XA", "XB", "XC", "XD", "XE", "XF", "XG", "XH", "XI", "XK", "XL", "XM",
    # Y  Musik, Theater, Film, Tanz
    "YA", "YB", "YC", "YD", "YE", "YF", "YG", "YH", "YI", "YK",
    # Z  Mathematik
    "ZA", "ZB", "ZC", "ZD", "ZE", "ZF", "ZG", "ZH", "ZI", "ZK", "ZL", "ZM",
    "ZN", "ZO", "ZP", "ZQ", "ZR", "ZS", "ZT", "ZU", "ZV", "ZW", "ZX",
    # 3-letter prefixes for specific areas
    "ACH", "ACV",
}


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Find and store RVK notations for a document.

    Returns list of notation strings found.
    """
    # Step 1: local detection
    notations = _detect_local_notations(conn, document_id)

    # Step 2: API lookup if nothing found locally
    if not notations:
        notations = _lookup_via_api(conn, document_id)

    if notations:
        _write_notations(conn, document_id, notations)

    return notations


def label_for_notation(notation: str) -> str | None:
    """Fetch the German label for an RVK notation from the API.

    e.g. 'ZH 5500' → 'Historische Gebäude und Denkmäler'
    Returns None if the API is unavailable or notation not found.
    """
    notation_clean = notation.strip().replace(" ", "%20")
    url = f"{_RVK_API}/node/{urllib.parse.quote(notation_clean)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("node", {}).get("benennung")
    except Exception as exc:
        log.debug("RVK label lookup failed for %r: %s", notation, exc)
        return None


def search_notation(query: str, max_results: int = 5) -> list[dict]:
    """Search RVK for notations matching a keyword query.

    Returns list of {"notation": str, "label": str, "hierarchy": str}
    """
    url = f"{_RVK_API}/search/{urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        log.debug("RVK search failed for %r: %s", query, exc)
        return []

    results = []
    for item in data.get("results", {}).get("result", [])[:max_results]:
        notation = item.get("notation", "")
        label    = item.get("benennung", "")
        hier     = item.get("ancestor-notations", "")
        if notation:
            results.append({
                "notation":  notation,
                "label":     label,
                "hierarchy": hier,
            })
    return results


# ── Local detection ───────────────────────────────────────────────────────────

def _detect_local_notations(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Scan early document blocks for RVK notation strings."""
    # Look in the first 30 blocks (front matter / title page area)
    rows = conn.execute(
        """
        SELECT b.text
        FROM du_blocks b
        WHERE b.document_id = ? AND b.block_index <= 30
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()

    notations: list[str] = []
    seen: set[str] = set()

    for row in rows:
        text = row["text"] or ""
        for m in _RVK_NOTATION_RE.finditer(text):
            # Validate: first group is letters, second is digits
            letters = m.group(1)
            digits  = m.group(2)
            notation = f"{letters} {digits}"
            if notation not in seen and _looks_like_rvk(letters, digits):
                seen.add(notation)
                notations.append(notation)

    return notations


def _looks_like_rvk(letters: str, digits: str) -> bool:
    """Validate against known RVK subject group prefixes."""
    if letters not in _RVK_VALID_PREFIXES:
        return False
    n = int(digits)
    return 100 <= n <= 99999


# ── API lookup ────────────────────────────────────────────────────────────────

def _lookup_via_api(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Search RVK API using document title and keywords."""
    row = conn.execute(
        "SELECT title, keywords FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    if not row:
        return []

    # Build search query from title + keywords
    title = row["title"] or ""
    keywords: list[str] = []
    if row["keywords"]:
        try:
            keywords = json.loads(row["keywords"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Use up to 3 most informative terms
    search_terms = (keywords[:2] + [title.split()[:5]])
    query_parts  = []
    for term in search_terms:
        if isinstance(term, list):
            query_parts.append(" ".join(term))
        elif isinstance(term, str) and term.strip():
            query_parts.append(term.strip())

    if not query_parts:
        return []

    query = " ".join(query_parts)[:100]
    results = search_notation(query, max_results=3)
    time.sleep(_SLEEP)

    if not results:
        return []

    # Return the top result's notation
    return [results[0]["notation"]]


# ── Database write ────────────────────────────────────────────────────────────

def _write_notations(
    conn: sqlite3.Connection,
    document_id: str,
    notations: list[str],
) -> None:
    """Write RVK notations to document_identifiers table."""
    for notation in notations:
        conn.execute(
            """
            INSERT INTO document_identifiers
                (document_id, identifier_type, identifier_value)
            VALUES (?, 'rvk', ?)
            ON CONFLICT DO NOTHING
            """,
            (document_id, notation),
        )
    conn.commit()
