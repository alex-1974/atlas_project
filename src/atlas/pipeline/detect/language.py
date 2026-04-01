# src/atlas/pipeline/detect/language.py
"""Language detection for Atlas documents.

Uses the `lingua` library for offline, high-accuracy language detection.
Handles multilingual documents by returning a primary language and optional
secondary language when a significant portion of the text differs.

Language codes follow ISO 639-1 (e.g. 'en', 'de', 'fr').

Note: A document's text language does not imply the author's nationality.
A Swiss researcher may write in English; a German report may quote French
sources. Language detection informs tokenisation, OCR, and name-list
selection — not metadata attribution.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Minimum confidence threshold for a secondary language to be reported.
# Below this value the secondary language is noise, not a real second language.
_SECONDARY_THRESHOLD = 0.15

# Maximum number of characters to use for detection (for performance).
# Body text only — skip front matter which often contains multilingual headers.
_SAMPLE_CHARS = 2000

# Languages supported for detection. Expanding this list increases accuracy
# but also increases memory usage and startup time.
_SUPPORTED_LANGUAGES = None  # lazy-initialised


@dataclass
class LanguageResult:
    primary: str          # ISO 639-1 code, e.g. 'en'
    secondary: str | None # ISO 639-1 code if multilingual, else None
    confidence: float     # confidence of primary detection (0–1)
    is_multilingual: bool


def detect_language(text: str) -> LanguageResult:
    """Detect the primary (and optional secondary) language of a text sample.

    Returns English with low confidence if detection fails or lingua is
    not installed.
    """
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        return LanguageResult(
            primary="en", secondary=None, confidence=0.5, is_multilingual=False
        )

    global _SUPPORTED_LANGUAGES
    if _SUPPORTED_LANGUAGES is None:
        _SUPPORTED_LANGUAGES = [
            Language.ENGLISH, Language.GERMAN, Language.FRENCH,
            Language.DUTCH, Language.ITALIAN, Language.SPANISH,
            Language.PORTUGUESE,
        ]

    detector = LanguageDetectorBuilder.from_languages(
        *_SUPPORTED_LANGUAGES
    ).build()

    sample = text[:_SAMPLE_CHARS].strip()
    if not sample:
        return LanguageResult(
            primary="en", secondary=None, confidence=0.5, is_multilingual=False
        )

    results = detector.compute_language_confidence_values(sample)
    if not results:
        return LanguageResult(
            primary="en", secondary=None, confidence=0.5, is_multilingual=False
        )

    # Sort by confidence descending
    sorted_results = sorted(results, key=lambda r: r.value, reverse=True)
    primary_lang = sorted_results[0].language
    primary_conf = sorted_results[0].value
    primary_code = _to_iso(primary_lang)

    # Check for significant secondary language
    secondary_code = None
    is_multilingual = False
    if len(sorted_results) > 1:
        second_conf = sorted_results[1].value
        if second_conf >= _SECONDARY_THRESHOLD:
            secondary_code = _to_iso(sorted_results[1].language)
            is_multilingual = True

    return LanguageResult(
        primary=primary_code,
        secondary=secondary_code,
        confidence=primary_conf,
        is_multilingual=is_multilingual,
    )


def run_detect_language(conn: sqlite3.Connection, document_id: str) -> None:
    """Detect document language and write to documents.language.

    Uses body text from du_block_roles (role='body') for reliable detection —
    body text is more representative than front matter which may contain
    multilingual boilerplate (publisher info, copyright notices, etc.).

    For multilingual documents, stores the primary language code and logs
    the secondary language in the pipeline notes.
    """
    # Get body text sample from DU blocks
    body_rows = conn.execute(
        """
        SELECT b.text
        FROM du_block_roles r
        JOIN du_blocks b ON b.block_id = r.block_id
        WHERE b.document_id = ? AND r.role = 'body'
        ORDER BY b.block_index
        LIMIT 20
        """,
        (document_id,),
    ).fetchall()

    if not body_rows:
        # Fallback to raw extracted text
        text_row = conn.execute(
            "SELECT text FROM extracted_texts WHERE document_id = ? LIMIT 1",
            (document_id,),
        ).fetchone()
        sample = (text_row["text"] or "")[:_SAMPLE_CHARS] if text_row else ""
    else:
        sample = " ".join(r["text"] or "" for r in body_rows)

    if not sample.strip():
        return

    result = detect_language(sample)

    # Only write if not already set (or if set to placeholder)
    existing = conn.execute(
        "SELECT language FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()

    if existing and existing["language"] and existing["language"] not in ("", "unknown"):
        return  # already detected — don't overwrite manual/enriched value

    conn.execute(
        "UPDATE documents SET language = ? WHERE document_id = ?",
        (result.primary, document_id),
    )
    conn.commit()


# ── ISO 639-1 mapping ─────────────────────────────────────────────────────────

_LINGUA_TO_ISO: dict[str, str] = {
    "ENGLISH":    "en",
    "GERMAN":     "de",
    "FRENCH":     "fr",
    "DUTCH":      "nl",
    "ITALIAN":    "it",
    "SPANISH":    "es",
    "PORTUGUESE": "pt",
    "LATIN":      "la",
}


def _to_iso(language) -> str:
    return _LINGUA_TO_ISO.get(language.name, language.name.lower()[:2])
