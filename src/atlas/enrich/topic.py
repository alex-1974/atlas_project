# src/atlas/enrich/topic.py
"""Topic extraction — one descriptive sentence per document.

Topic vs. Keywords
------------------
Topic  = "Was ist dieses Dokument?" — ein kohärenter Satz
Keywords = "Welche Terme sind wichtig?" — diskrete Terme

Topic-Extraktion ist extractive (kein LLM nötig):
Der erste informative Body-Block nach dem Titel ist bei
wissenschaftlichen und historischen Dokumenten meistens
der beste Topic-Kandidat — er fasst den Dokumentinhalt
in einem Satz zusammen.

Extraktionskette:
    1. Expliziter Abstract-Block (falls vorhanden)
    2. Erster langer Body-Block (≥ 15 Wörter) auf Seite 0-1
    3. Zusammengesetzt aus Titel + ersten 2 Headings
    4. Titel allein als Fallback

Schreibt in:
    documents.topic (TEXT)
    Oxigraph: atlas:topic Tripel (optional)
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

log = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_topic(
    conn: sqlite3.Connection,
    document_id: str,
    store=None,
    force: bool = False,
) -> str | None:
    """Extract and store a topic sentence for a document.

    Returns the topic string, or None if extraction failed.
    """
    # Skip if already extracted
    if not force:
        row = conn.execute(
            "SELECT topic FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row and row["topic"]:
            return row["topic"]

    topic = (
        _topic_from_abstract_block(conn, document_id)
        or _topic_from_first_body_block(conn, document_id)
        or _topic_from_title_and_headings(conn, document_id)
        or _topic_from_title(conn, document_id)
    )

    if topic:
        topic = _clean_topic(topic)
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


# ── Extraction methods ────────────────────────────────────────────────────────

def _topic_from_abstract_block(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Use the abstract block if explicitly marked."""
    # Check stored abstract first
    row = conn.execute(
        "SELECT abstract FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row and row["abstract"] and len(row["abstract"].split()) >= 10:
        # First sentence of abstract
        return _first_sentence(row["abstract"])

    # Look for abstract marker in DU output
    marker = conn.execute(
        """
        SELECT b.block_index FROM du_block_semantic_micro sm
        JOIN du_blocks b ON b.block_id = sm.block_id
        WHERE b.document_id = ? AND sm.is_abstract_marker = 1
        ORDER BY b.block_index LIMIT 1
        """,
        (document_id,),
    ).fetchone()

    if not marker:
        return None

    # Get the block(s) immediately after the abstract marker
    abstract_blocks = conn.execute(
        """
        SELECT b.text FROM du_blocks b
        JOIN du_block_roles r ON r.block_id = b.block_id
        WHERE b.document_id = ?
          AND b.block_index > ?
          AND b.block_index <= ?
          AND r.role = 'body'
        ORDER BY b.block_index
        LIMIT 3
        """,
        (document_id, marker["block_index"], marker["block_index"] + 5),
    ).fetchall()

    if not abstract_blocks:
        return None

    text = " ".join(b["text"] or "" for b in abstract_blocks).strip()
    if len(text.split()) >= 10:
        return _first_sentence(text)
    return None


def _topic_from_first_body_block(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Use the first substantial body block in the body zone.

    For articles: typically on pages 0-2.
    For monographs: may be much later (after copyright pages, preface, ToC).
    Uses du_block_zones to find blocks in the 'body' zone rather than
    relying on page numbers.
    """
    # Try zone-based selection first (more reliable for monographs)
    rows = conn.execute(
        """
        SELECT b.text, b.page_index FROM du_blocks b
        JOIN du_block_roles r ON r.block_id = b.block_id
        JOIN du_block_zones z ON z.block_id = b.block_id
        WHERE b.document_id = ?
          AND r.role = 'body'
          AND z.zone IN ('body', 'abstract')
        ORDER BY b.block_index
        LIMIT 40
        """,
        (document_id,),
    ).fetchall()

    # Fallback: first pages (for documents without zone data)
    if not rows:
        rows = conn.execute(
            """
            SELECT b.text, b.page_index FROM du_blocks b
            JOIN du_block_roles r ON r.block_id = b.block_id
            WHERE b.document_id = ?
              AND r.role = 'body'
              AND b.page_index <= 5
            ORDER BY b.block_index
            LIMIT 40
            """,
            (document_id,),
        ).fetchall()

    for row in rows:
        text = (row["text"] or "").strip()
        words = text.split()
        if len(words) >= 15:
            if _is_metadata_text(text):
                continue
            return _first_sentence(text) or text[:200]

    return None


def _topic_from_title_and_headings(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Compose topic from title + first two L1 headings."""
    doc = conn.execute(
        "SELECT title FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if not doc or not doc["title"]:
        return None

    title = doc["title"].strip()

    headings = conn.execute(
        """
        SELECT title FROM du_section_tree
        WHERE document_id = ? AND level = 1
        ORDER BY start_block_index
        LIMIT 3
        """,
        (document_id,),
    ).fetchall()

    heading_texts = [
        h["title"] for h in headings
        if h["title"] and not _is_structural_heading(h["title"])
    ][:2]

    if heading_texts:
        return f"{title}. Kapitel: {', '.join(heading_texts)}."
    return title


def _topic_from_title(
    conn: sqlite3.Connection,
    document_id: str,
) -> str | None:
    """Fallback: use the document title."""
    row = conn.execute(
        "SELECT title FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row and row["title"]:
        return row["title"].strip()
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _first_sentence(text: str) -> str | None:
    """Extract the first sentence from a text block.

    Also handles the common case where letter-spaced text loses its
    first character ('HE FOUNDATION' → likely 'THE FOUNDATION').
    """
    text = " ".join(text.split())

    # Heuristic: if text starts with a lowercase-like fragment after
    # letter-spacing normalization, prepend likely missing capital
    # e.g. 'HE FOUNDATION' → DU lost 'T'
    # We can't reliably recover the missing letter, so we just
    # clean up and use what we have.

    match = re.search(r'[.!?](?:\s|$)', text)
    if match and match.start() > 20:
        sentence = text[:match.start() + 1].strip()
        if len(sentence.split()) >= 8:
            return sentence
    if len(text.split()) >= 15:
        return text[:200].strip()
    return None


def _is_metadata_text(text: str) -> bool:
    """True if text looks like metadata rather than content."""
    lower = text.lower()
    # Normalize unicode quotes for pattern matching
    normalized = (text
        .replace('\u2018', "'").replace('\u2019', "'")
        .replace('\u201c', '"').replace('\u201d', '"')
        .replace('\u2032', "'"))

    patterns = [
        r'^\d+\s*$',                            # page numbers
        r'^vol\.\s*\d+',                         # volume info
        r'doi:\s*10\.',                          # DOI
        r'issn\s*[\d-]',                        # ISSN
        r'©\s*\d{4}',                           # copyright
        r'^(figure|fig\.|table|tab\.)',          # captions
        r'^\w+\s+\d{4};\s*\d+',                # journal citation format
        r"[A-Za-z].{0,40},\s*['\"]",           # author, 'Title' citation
        r'content\s*©',                          # content copyright
        r'all rights reserved',                  # rights statement
        r'made available for.*research',         # access statement
        r'digitised by',                         # digitisation note
        r'extracted from',                       # extraction note
        r'may be reproduced',                    # copyright disclaimer
        r'no part of this',                      # copyright disclaimer
        r'stored in a retrieval',                # copyright disclaimer
        r'new series\s+\d+',                     # journal series ref
        r'book of the',                          # journal title ref
    ]
    text_to_check = normalized.lower()
    for pattern in patterns:
        if re.search(pattern, text_to_check):
            return True

    # Caption pattern: "Term, description. Proper noun" without full sentences
    # e.g. "Niederdeutsches Hallenhaus, Schaubild und Grundriss. Hof Große-..."
    words = text.split()
    if len(words) >= 5:
        # High ratio of proper nouns / capitalized words suggests caption
        cap_ratio = sum(1 for w in words if w and w[0].isupper()) / len(words)
        # Very short lines (average < 4 words per line) suggest caption layout
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        avg_words_per_line = len(words) / max(len(lines), 1)
        if cap_ratio > 0.6 and avg_words_per_line < 5 and len(words) < 30:
            return True

    digit_ratio = sum(1 for c in text if c.isdigit()) / max(len(text), 1)
    return digit_ratio > 0.25


def _is_structural_heading(text: str) -> bool:
    """True if heading is structural rather than thematic."""
    structural = {
        "references", "bibliography", "appendix", "acknowledgements",
        "contents", "index", "abstract", "introduction", "conclusion",
        "literatur", "anhang", "einleitung", "zusammenfassung",
    }
    return text.lower().strip().rstrip('.') in structural


def _clean_topic(topic: str) -> str:
    """Normalise whitespace and strip edge artefacts."""
    topic = " ".join(topic.split())
    topic = topic.strip('.,;:')
    return topic[:500]  # hard cap


# ── Database and graph writes ─────────────────────────────────────────────────

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
        log.debug("Could not write topic (run atlas dev db migrate): %s", exc)


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
