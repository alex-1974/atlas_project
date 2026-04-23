"""
atlas.semantic.persist

Schreibt Ergebnisse des semantic-Stacks in SQLite.

Schreibt:
  du_section_keywords  — Keywords pro Abschnitt
  document_identifiers — GND-IDs pro Dokument (aggregiert aus Abschnitten)
  documents.keywords   — aggregierte Dokument-Keywords (Top-N aus allen Abschnitten)
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter

from .keywords import SectionKeywords


def save_section_keywords(
    conn: sqlite3.Connection,
    document_id: str,
    section_keywords: dict[int | None, SectionKeywords],
    force: bool = False,
) -> int:
    """
    Schreibt Section-Keywords in du_section_keywords.

    Args:
        conn:             SQLite-Verbindung
        document_id:      Dokument-ID
        section_keywords: Ausgabe von semantic.keywords.extract_keywords()
        force:            Bestehende Einträge überschreiben

    Returns:
        Anzahl geschriebener Einträge
    """
    if not force:
        existing = conn.execute(
            "SELECT COUNT(*) FROM du_section_keywords WHERE document_id = ?",
            (document_id,),
        ).fetchone()[0]
        if existing > 0:
            return 0

    written = 0
    for node_id, sk in section_keywords.items():
        if node_id is None or not sk.keywords:
            continue
        conn.execute(
            """
            INSERT INTO du_section_keywords
                (section_node_id, document_id, keywords, keyword_method)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(section_node_id) DO UPDATE SET
                keywords       = excluded.keywords,
                keyword_method = excluded.keyword_method,
                extracted_at   = datetime('now')
            """,
            (
                node_id,
                document_id,
                json.dumps(sk.keywords, ensure_ascii=False),
                f"{sk.method}:{sk.language}",
            ),
        )
        written += 1

    conn.commit()
    return written


def save_gnd_hits(
    conn: sqlite3.Connection,
    document_id: str,
    gnd_hits: dict[int | None, list[dict]],
) -> int:
    """
    Schreibt GND-IDs aus Section-Enrichment in document_identifiers.

    Dedupliziert über alle Abschnitte — jede GND-ID nur einmal pro Dokument.

    Returns:
        Anzahl neu geschriebener GND-Einträge
    """
    seen: set[str] = set()
    # Bestehende GND-IDs aus DB laden
    existing = conn.execute(
        "SELECT identifier_value FROM document_identifiers "
        "WHERE document_id = ? AND identifier_type = 'gnd'",
        (document_id,),
    ).fetchall()
    for row in existing:
        seen.add(row[0])

    written = 0
    for node_id, hits in gnd_hits.items():
        for hit in hits:
            gid = hit.get("gnd_id", "")
            if not gid or gid in seen:
                continue
            seen.add(gid)
            conn.execute(
                """
                INSERT INTO document_identifiers
                    (document_id, identifier_type, identifier_value)
                VALUES (?, 'gnd', ?)
                ON CONFLICT DO NOTHING
                """,
                (document_id, gid),
            )
            written += 1

    conn.commit()
    return written


def aggregate_document_keywords(
    section_keywords: dict[int | None, SectionKeywords],
    max_keywords: int = 15,
) -> list[str]:
    """
    Aggregiert Section-Keywords zu Dokument-Keywords.

    Strategie: Häufigste Keywords über alle Abschnitte,
    L1-Abschnitte doppelt gewichtet.

    Returns:
        Liste der Top-N Dokument-Keywords
    """
    from .section_text import SectionText  # nur für Type-Hint

    counts: Counter = Counter()
    for node_id, sk in section_keywords.items():
        weight = 2 if sk.keywords else 1
        for kw in sk.keywords:
            counts[kw.lower()] += weight

    # Normalisierung: Lemma-Varianten zusammenführen
    # (z.B. "Hallenhaus" und "hallenhaus" sind dasselbe)
    top = [kw for kw, _ in counts.most_common(max_keywords * 2)]

    # Duplikate durch case-insensitive Vergleich entfernen
    seen: set[str] = set()
    result: list[str] = []
    for kw in top:
        if kw not in seen:
            seen.add(kw)
            # Originale Großschreibung aus section_keywords wiederherstellen
            for sk in section_keywords.values():
                original = next((k for k in sk.keywords
                                 if k.lower() == kw), None)
                if original:
                    result.append(original)
                    break
        if len(result) >= max_keywords:
            break

    return result


def save_document_keywords(
    conn: sqlite3.Connection,
    document_id: str,
    keywords: list[str],
    force: bool = False,
) -> None:
    """Schreibt aggregierte Keywords in documents.keywords."""
    if not force:
        existing = conn.execute(
            "SELECT keywords FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if existing and existing[0]:
            return  # Bereits vorhanden

    conn.execute(
        "UPDATE documents SET keywords = ? WHERE document_id = ?",
        (json.dumps(keywords, ensure_ascii=False), document_id),
    )
    conn.commit()
