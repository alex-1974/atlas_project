# src/atlas/enrich/keywords.py
"""Keyword extraction — two-tier approach.

Tier 1 — YAKE (fast, offline, no corpus needed)
    Used automatically during `atlas add` and `atlas enrich --keywords`.
    YAKE (Yet Another Keyword Extractor) uses local statistical features
    of a single document: term position, casing, frequency, context window.
    Language-independent — works on English and German without configuration.
    pip install yake

Tier 2 — KeyBERT (semantic, uses existing embedding model)
    Optional. Run with `atlas enrich --keywords-semantic`.
    Reuses the all-MiniLM-L6-v2 model already loaded for LanceDB embeddings.
    Finds n-gram phrases whose embedding is most similar to the document
    embedding — captures synonyms and paraphrases that YAKE misses.
    pip install keybert

Design
------
Explicit keywords (from a "Keywords:" block) always take priority.
YAKE runs on title + headings + body sample.
KeyBERT runs on the same text and re-ranks / augments YAKE results.
Results are stored in documents.keywords (JSON array).
"""
from __future__ import annotations

import json
import re
import sqlite3
import string
import logging

log = logging.getLogger(__name__)

# YAKE score: lower = more relevant. Threshold above which we discard.
_YAKE_SCORE_THRESHOLD = 0.35

# Patterns indicating metadata — used by _clean_keywords
_NOISE_RE = re.compile(
    r'\bISSN\b|DOI\s*:|https?://|\d{4}-\d{4}|\bvol\b|\bno\.\b',
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_keywords(
    conn: sqlite3.Connection,
    document_id: str,
    store=None,
    use_yake: bool = True,
) -> list[str]:
    """Extract keywords for a document and write to SQLite.

    Priority:
        1. Explicit keywords block in the document
        2. KeyBERT (if sentence-transformers already loaded — reuses model)
        3. YAKE (if installed: pip install yake)
        4. TF-IDF fallback (always available)

    If store (KnowledgeStore) is provided, also writes
    atlas:has_keyword triples.

    Returns the extracted keyword list.
    """
    # 1. Explicit keywords from a "Keywords:" block
    keywords = _extract_explicit_keywords(conn, document_id)

    if not keywords:
        # 2. KeyBERT — preferred when model is already loaded
        if _keybert_model_available():
            keywords = _extract_with_keybert(conn, document_id)

        # 3. YAKE fallback
        if not keywords and use_yake:
            keywords = _extract_with_yake(conn, document_id)

        # 4. TF-IDF last resort
        if not keywords:
            keywords = _extract_with_tfidf(conn, document_id)

    if keywords:
        _write_keywords(conn, document_id, keywords)
        if store is not None:
            _write_keyword_triples(store, document_id, keywords)

    return keywords


def _keybert_model_available() -> bool:
    """True if KeyBERT and the embedding model are already loaded."""
    try:
        from keybert import KeyBERT  # noqa: F401
        # Check if model is already in memory — don't load it just for keywords
        import sys
        if 'atlas.embeddings.model' in sys.modules:
            from atlas.embeddings.model import _model
            return _model is not None
        return False
    except ImportError:
        return False


def extract_keywords_semantic(
    conn: sqlite3.Connection,
    document_id: str,
    store=None,
) -> list[str]:
    """Re-extract keywords using KeyBERT (semantic, higher quality).

    Requires: pip install keybert
    Reuses the all-MiniLM-L6-v2 model from atlas.embeddings.model.
    Overwrites existing keywords.

    Returns the extracted keyword list.
    """
    keywords = _extract_with_keybert(conn, document_id)
    if keywords:
        _write_keywords(conn, document_id, keywords)
        if store is not None:
            _write_keyword_triples(store, document_id, keywords)
    return keywords


def keywords_for_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Return stored keywords, extracting with YAKE if not yet present."""
    row = conn.execute(
        "SELECT keywords FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if row and row["keywords"]:
        try:
            kws = json.loads(row["keywords"])
            if isinstance(kws, list) and kws:
                return kws
        except (json.JSONDecodeError, TypeError):
            pass
    return extract_keywords(conn, document_id)


# ── Explicit keyword extraction ───────────────────────────────────────────────

def _extract_explicit_keywords(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Extract keywords from a 'Keywords:' section if present."""
    marker_rows = conn.execute(
        """
        SELECT b.block_index
        FROM du_block_semantic_micro sm
        JOIN du_blocks b ON b.block_id = sm.block_id
        WHERE b.document_id = ? AND sm.is_keywords_marker = 1
        ORDER BY b.block_index LIMIT 1
        """,
        (document_id,),
    ).fetchall()

    if not marker_rows:
        return []

    marker_idx = marker_rows[0]["block_index"]
    candidate_rows = conn.execute(
        """
        SELECT b.text FROM du_blocks b
        WHERE b.document_id = ? AND b.block_index > ?
          AND b.block_index <= ?
        ORDER BY b.block_index
        """,
        (document_id, marker_idx, marker_idx + 3),
    ).fetchall()

    keywords = []
    for row in candidate_rows:
        text = (row["text"] or "").strip()
        if not text:
            continue
        # Stop at a new heading
        if len(text.split()) <= 4 and text == text.upper() and text.isalpha():
            break
        kws = _split_keyword_string(text)
        keywords.extend(kws)
        if kws:
            break

    return _clean_keywords(keywords)


def _split_keyword_string(text: str) -> list[str]:
    """Split a keyword string on ; or ,"""
    text = re.sub(r'^\s*[•·–\-]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n', '; ', text)
    if ';' in text:
        parts = text.split(';')
    elif ',' in text and text.count(',') >= 2:
        parts = text.split(',')
    else:
        parts = [text]
    return [p.strip() for p in parts if p.strip()]


# ── YAKE extraction ───────────────────────────────────────────────────────────

def _extract_with_yake(
    conn: sqlite3.Connection,
    document_id: str,
    max_keywords: int = 10,
) -> list[str]:
    """Extract keywords using YAKE (requires pip install yake)."""
    try:
        import yake as _yake
    except ImportError:
        log.debug("yake not installed — falling back to TF-IDF")
        return []

    text, lang = _build_document_text(conn, document_id)
    if not text or len(text.split()) < 10:
        return []

    # YAKE parameters — tuned for academic/heritage documents:
    # n=2: bigrams only — trigrams cause phantom repetitions on repeated headings
    # dedupLim=0.4: aggressive deduplication (lower = stricter)
    # windowsSize=2: context window
    kw_extractor = _yake.KeywordExtractor(
        lan=lang,
        n=2,
        dedupLim=0.4,
        dedupFunc='seqm',
        windowsSize=2,
        top=max_keywords * 3,
        features=None,
    )

    try:
        raw = kw_extractor.extract_keywords(text)
    except Exception as exc:
        log.debug("YAKE extraction failed: %s", exc)
        return []

    # Filter by score threshold (lower = more relevant in YAKE)
    candidates = [kw for kw, score in raw if score <= _YAKE_SCORE_THRESHOLD]

    return _clean_keywords(candidates)[:max_keywords]


# ── KeyBERT extraction ────────────────────────────────────────────────────────

def _extract_with_keybert(
    conn: sqlite3.Connection,
    document_id: str,
    max_keywords: int = 10,
) -> list[str]:
    """Extract keywords using KeyBERT with the existing embedding model.

    Uses all-MiniLM-L6-v2 from atlas.embeddings.model (already loaded).
    Falls back to YAKE if KeyBERT is not installed.
    """
    try:
        from keybert import KeyBERT
    except ImportError:
        log.warning("keybert not installed. Run: pip install keybert")
        return _extract_with_yake(conn, document_id, max_keywords)

    text, _ = _build_document_text(conn, document_id)
    if not text or len(text.split()) < 20:
        return []

    # Reuse the embedding model already loaded for LanceDB
    try:
        from atlas.embeddings.model import get_model
        sentence_model = get_model()
        kw_model = KeyBERT(model=sentence_model)
    except Exception:
        # If embedding model not available, use KeyBERT default
        kw_model = KeyBERT()

    # Extract with Maximal Marginal Relevance for diversity
    # keyphrase_ngram_range=(1,3): single words to trigrams
    # use_mmr=True: diversify results
    # diversity=0.5: balance relevance vs diversity
    try:
        raw = kw_model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 3),
            stop_words='english',
            use_mmr=True,
            diversity=0.5,
            top_n=max_keywords * 2,
        )
    except Exception as exc:
        log.debug("KeyBERT extraction failed: %s", exc)
        return _extract_with_yake(conn, document_id, max_keywords)

    candidates = [kw for kw, score in raw if score >= 0.2]
    return _clean_keywords(candidates)[:max_keywords]


# ── TF-IDF fallback ───────────────────────────────────────────────────────────

def _extract_with_tfidf(
    conn: sqlite3.Connection,
    document_id: str,
    max_keywords: int = 8,
) -> list[str]:
    """TF-IDF fallback when YAKE is not installed."""
    import math

    text, _ = _build_document_text(conn, document_id)
    if not text:
        return []

    tf = _count_terms(text)
    if not tf:
        return []

    all_ids = [r["document_id"] for r in conn.execute(
        "SELECT document_id FROM documents WHERE pipeline_status = 'indexed'"
    ).fetchall()]
    N = len(all_ids)

    if N < 2:
        top = sorted(tf.items(), key=lambda x: -x[1])
        return _clean_keywords([t for t, _ in top[:max_keywords * 2]])[:max_keywords]

    candidates = [t for t, f in tf.items() if f >= 2][:150]
    df: dict[str, int] = {}
    for other_id in all_ids:
        if other_id == document_id:
            continue
        other_text, _ = _build_document_text(conn, other_id)
        other_terms = set(_count_terms(other_text).keys())
        for term in candidates:
            if term in other_terms:
                df[term] = df.get(term, 0) + 1

    scores = {
        t: tf[t] * (math.log((N + 1) / (df.get(t, 0) + 1)) + 1.0)
        for t in candidates
    }
    top_terms = [t for t, _ in sorted(scores.items(), key=lambda x: -x[1])]
    return _clean_keywords(top_terms[:max_keywords * 2])[:max_keywords]


# ── Text assembly ─────────────────────────────────────────────────────────────

def _build_document_text(
    conn: sqlite3.Connection,
    document_id: str,
) -> tuple[str, str]:
    """Build a representative text string for keyword extraction.

    Returns (text, language_code).
    - Title and headings weighted by repetition
    - Body sampled (first 60 blocks)
    - page_furniture and noise blocks excluded
    - Letter-spaced text normalized to readable form
    """
    doc_row = conn.execute(
        "SELECT title, language FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    lang = "en"
    parts: list[str] = []

    if doc_row:
        if doc_row["language"]:
            lang_map = {"de": "de", "fr": "fr", "nl": "nl", "it": "it",
                        "es": "es", "pt": "pt", "en": "en"}
            lang = lang_map.get((doc_row["language"] or "en")[:2], "en")
        if doc_row["title"]:
            # Title 3x — most reliable topic signal
            parts.extend([doc_row["title"]] * 3)

    # L1/L2 headings (2x weight) — normalized
    headings = conn.execute(
        "SELECT title FROM du_section_tree WHERE document_id = ? AND level <= 2",
        (document_id,),
    ).fetchall()
    for h in headings:
        if h["title"]:
            parts.extend([h["title"]] * 2)

    # Body blocks — exclude furniture and noise
    body_blocks = conn.execute(
        """
        SELECT b.text FROM du_blocks b
        JOIN du_block_roles r ON r.block_id = b.block_id
        WHERE b.document_id = ? AND r.role IN ('body', 'heading', 'caption')
        ORDER BY b.block_index LIMIT 80
        """,
        (document_id,),
    ).fetchall()
    for b in body_blocks:
        text = (b["text"] or "").strip()
        if not text:
            continue
        # Normalize letter-spaced text ('C A S T L E  H I L L' → 'CASTLE HILL')
        text = _normalize_text(text)
        parts.append(text)

    return " ".join(parts), lang


def _normalize_text(text: str) -> str:
    """Collapse letter-spaced text and normalize whitespace."""
    # Letter-spaced pattern: single chars separated by spaces
    _LS_RE = re.compile(
        r'^(?:[A-Za-z\u00C0-\u00FF]{1,3}|[–—\-])'
        r'(?:\s+(?:[A-Za-z\u00C0-\u00FF]{1,3}|[–—\-])){3,}\s*$'
    )
    lines = text.split('\n')
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        normalised = " ".join(line.split())
        if _LS_RE.match(normalised):
            # Collapse: remove all spaces between chars
            word_groups = re.split(r' {2,}', line)
            collapsed = " ".join("".join(g.split()) for g in word_groups if g.strip())
            result.append(collapsed)
        else:
            result.append(line)
    return " ".join(result)


def _count_terms(text: str) -> dict[str, int]:
    """Token frequency for TF-IDF fallback."""
    _STOPWORDS = {
        "the","a","an","and","or","of","in","on","at","to","for","with",
        "by","from","as","is","are","was","were","its","their","this",
        "that","these","those","some","into","about","between","through",
        "have","has","had","been","will","would","could","should","also",
        "more","such","which","when","where","than","then","there","here",
        "they","them","what","each","both","after","before","over","under",
        "while","during","within","without","against",
        "der","die","das","des","dem","den","ein","eine","und","oder",
        "von","zu","im","am","auf","an","mit","aus","für","über","nach",
        "bei","wird","sind","war","haben","kann","nicht","auch","einer",
    }
    counts: dict[str, int] = {}
    for word in re.findall(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b', text):
        term = word.lower()
        if term not in _STOPWORDS:
            counts[term] = counts.get(term, 0) + 1
    return counts


# ── Cleaning ──────────────────────────────────────────────────────────────────

def _clean_keywords(keywords: list[str]) -> list[str]:
    """Normalise, filter noise, deduplicate including inflected forms."""
    _UNICODE_PUNCT = '…"„"\u2018\u2019\u201c\u201d\u2014\u2013'
    _STRIP_CHARS   = string.punctuation + _UNICODE_PUNCT

    _NOISE_WORDS: set[str] = {
        "chapter", "section", "table", "figure", "result", "results",
        "conclusion", "conclusions", "introduction", "reference", "references",
        "abstract", "appendix", "contents", "index", "bibliography",
        "summary", "overview", "background", "preface", "foreword",
        "acknowledgement", "acknowledgements", "glossary", "notation",
        "notes", "note", "information",
        "kapitel", "abschnitt", "ergebnis", "fazit", "einleitung",
        "zusammenfassung", "anhang", "literatur", "inhalt", "vorwort",
        "determine", "wanted", "answer", "manual",
    }
    _NOISE_BIGRAMS: set[str] = {
        "reference information", "information reference",
        "references notes", "notes references", "notes and references",
        "chapter section", "table figure",
    }

    # Normalise edge punctuation and whitespace
    cleaned: list[str] = []
    for kw in keywords:
        kw = kw.strip(_STRIP_CHARS).strip()
        kw = " ".join(kw.split())
        if len(kw) < 4:
            continue
        cleaned.append(kw)

    # Noise filter
    filtered: list[str] = []
    for kw in cleaned:
        lower = kw.lower()
        if lower in _NOISE_WORDS or lower in _NOISE_BIGRAMS:
            continue
        if _NOISE_RE.search(kw):
            continue
        filtered.append(kw)

    # Prefer multi-word phrases; single words only if ≥ 6 chars
    multi  = [kw for kw in filtered if len(kw.split()) >= 2]
    single = [kw for kw in filtered if len(kw.split()) == 1 and len(kw) >= 6]
    ordered = multi + single

    # Dedup pass 1: exact case-insensitive — prefer mixed-case over ALL-CAPS
    seen_lower: dict[str, str] = {}
    for kw in ordered:
        lower = kw.lower()
        if lower not in seen_lower:
            seen_lower[lower] = kw
        else:
            existing = seen_lower[lower]
            if existing == existing.upper() and kw != kw.upper():
                seen_lower[lower] = kw

    deduped = list(seen_lower.values())

    # Dedup pass 2: inflection-aware — collapse forms sharing the same stem
    # e.g. 'Niederdeutsche Hallenhaus', 'Niederdeutsches Hallenhaus' → keep first
    return _dedup_inflected(deduped)[:20]


def _dedup_inflected(keywords: list[str]) -> list[str]:
    """Remove near-duplicate keywords that differ only in inflection.

    Uses character-level truncation to approximate stemming without a
    language-specific stemmer. Keeps the form that appears first.

    Strategy: truncate each word to min(len, 10) chars — stable across
    German case endings (-e, -es, -en, -er) and English plurals (-s, -es).
    """
    def _stem(word: str) -> str:
        return word.lower()[:min(len(word), 10)]

    def _phrase_stem(phrase: str) -> str:
        return " ".join(_stem(w) for w in phrase.split())

    seen_stems: dict[str, str] = {}
    result: list[str] = []
    for kw in keywords:
        stem = _phrase_stem(kw)
        if stem not in seen_stems:
            seen_stems[stem] = kw
            result.append(kw)
    return result


# ── Database writes ───────────────────────────────────────────────────────────

def _write_keywords(
    conn: sqlite3.Connection,
    document_id: str,
    keywords: list[str],
) -> None:
    conn.execute(
        "UPDATE documents SET keywords = ? WHERE document_id = ?",
        (json.dumps(keywords, ensure_ascii=False), document_id),
    )
    conn.commit()


def _write_keyword_triples(
    store,
    document_id: str,
    keywords: list[str],
) -> None:
    """Write atlas:has_keyword triples to the knowledge graph."""
    try:
        from atlas.knowledge.store import P, doc_uri, KnowledgeStore, _slugify
        from pyoxigraph import NamedNode
        doc    = doc_uri(document_id)
        kw_pred = NamedNode("https://atlas.local/ontology#has_keyword")
        triples = []
        for kw in keywords:
            kw_node = NamedNode("https://atlas.local/keyword/" + _slugify(kw))
            triples.append((doc, kw_pred, kw_node))
            triples.append((kw_node, P["label"], KnowledgeStore.lit(kw)))
        store.add_doc_triples(document_id, triples)
    except Exception as exc:
        log.debug("Keyword triple write failed: %s", exc)
