"""
atlas.semantic.keywords

Keyword-Extraktion pro Abschnitt mit i18n-Unterstützung.

Eingabe:  dict[section_node_id, SectionText]
Ausgabe:  dict[section_node_id, list[str]]

Pipeline:
    1. Sprache pro Abschnitt erkennen (lingua, offline)
    2. YAKE mit sprachspezifischen Stopwörtern
    3. Bereinigung + Deduplizierung

Unterstützte Sprachen: DE, EN, FR, NL, IT, LA (Fallback: EN)
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

from .section_text import SectionText

import logging
logger = logging.getLogger(__name__)

_MAX_KW_PER_SECTION = 8
_MIN_WORDS_FOR_YAKE = 25

# Stopwörter pro Sprache — ergänzen YAKE's interne Listen
_STOPWORDS: dict[str, set[str]] = {
    "en": {
        "figure", "table", "section", "chapter", "appendix", "reference",
        "introduction", "conclusion", "also", "however", "therefore",
        "shown", "used", "using", "often", "well", "may", "can",
        "see", "fig", "ibid", "note", "notes",
    },
    "de": {
        "abbildung", "tabelle", "abschnitt", "kapitel", "anhang",
        "literatur", "einleitung", "zusammenfassung", "auch", "jedoch",
        "daher", "wird", "wurde", "werden", "vgl", "bzw", "abb",
        "ebd", "ebenso", "hierbei", "sowie", "dabei",
    },
    "fr": {
        "figure", "tableau", "section", "chapitre", "annexe",
        "introduction", "conclusion", "aussi", "cependant", "donc",
        "fig", "voir", "ibid", "cf",
    },
    "nl": {
        "figuur", "tabel", "sectie", "hoofdstuk", "bijlage",
        "inleiding", "conclusie", "ook", "echter", "daarom",
        "zie", "vgl",
    },
    "it": {
        "figura", "tabella", "sezione", "capitolo", "appendice",
        "introduzione", "conclusione", "anche", "tuttavia", "quindi",
        "fig", "vedi", "cfr",
    },
}

_PUNCT_STRIP = string.punctuation + '…"„"\u2018\u2019\u2014\u2013'


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class SectionKeywords:
    """Keywords eines Abschnitts mit Metadaten."""
    section_node_id: int | None
    title: str
    keywords: list[str] = field(default_factory=list)
    language: str = "en"
    method: str = "yake"


# ---------------------------------------------------------------------------
# Spracherkennung
# ---------------------------------------------------------------------------

def _detect_language(text: str) -> str:
    """Erkennt die Sprache eines Textes. Fallback: 'en'."""
    try:
        from lingua import Language, LanguageDetectorBuilder
        detector = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.GERMAN, Language.FRENCH,
            Language.DUTCH, Language.ITALIAN, Language.LATIN,
        ).build()
        lang = detector.detect_language_of(text[:500])
        if lang is None:
            return "en"
        return lang.iso_code_639_1.name.lower()
    except Exception:
        return "en"


# ---------------------------------------------------------------------------
# YAKE-Extraktion
# ---------------------------------------------------------------------------

def _yake_keywords(
    text: str,
    title: str,
    language: str,
    n_keywords: int,
) -> list[str]:
    """Extrahiert Keywords mit YAKE.

    Zwei Läufe:
      1. Bigramme (n=2) — Fachbegriffe wie "timber frame", "Niederdeutsches Hallenhaus"
      2. Unigramme (n=1) — einzelne Fachbegriffe die YAKE als Bigramm verpasst

    Beide Listen werden zusammengeführt, Bigramme bevorzugt.
    """
    try:
        import yake as _yake
    except ImportError:
        logger.debug("yake nicht installiert — Fallback zu Frequenz")
        return _freq_fallback(text, language, n_keywords)

    lang_map = {"de": "de", "fr": "fr", "nl": "nl", "it": "it"}
    yake_lang = lang_map.get(language, "en")

    # Titel 3× voranstellen um Abschnittsthema zu gewichten
    weighted = (f"{title} " * 3 + text) if title else text

    def _run(n: int, top: int) -> list[tuple[str, float]]:
        ext = _yake.KeywordExtractor(
            lan=yake_lang, n=n,
            dedupLim=0.5, dedupFunc="seqm",
            windowsSize=2, top=top,
        )
        try:
            return ext.extract_keywords(weighted)
        except Exception as exc:
            logger.debug("YAKE n=%d fehlgeschlagen: %s", n, exc)
            return []

    # Beide Läufe — YAKE-Score ist vergleichbar quer über n
    bi_raw  = _run(n=2, top=n_keywords * 4)
    uni_raw = _run(n=1, top=n_keywords * 4)

    # Zusammenführen: Bigramme die echte Mehrwörter sind bevorzugen
    # (YAKE gibt manchmal Unigramme auch bei n=2 zurück)
    seen: set[str] = set()
    combined: list[str] = []

    # Erst echte Bigramme (zwei Wörter)
    for kw, score in bi_raw:
        if len(kw.split()) >= 2 and kw.lower() not in seen:
            seen.add(kw.lower())
            combined.append(kw)

    # Dann Unigramme (aus beiden Läufen, nach Score sortiert)
    all_uni = sorted(
        {kw: sc for kw, sc in uni_raw + bi_raw
         if len(kw.split()) == 1}.items(),
        key=lambda x: x[1]
    )
    for kw, score in all_uni:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            combined.append(kw)

    return combined


def _freq_fallback(text: str, language: str, n: int) -> list[str]:
    """Einfacher Häufigkeits-Fallback wenn YAKE nicht verfügbar."""
    from collections import Counter
    stops = _STOPWORDS.get(language, _STOPWORDS["en"])
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜßàâéèêîïôùûœçÀÂÉÈÊÎÏÔÙÛŒÇ]{5,}\b',
                       text.lower())
    filtered = [w for w in words if w not in stops]
    return [w for w, _ in Counter(filtered).most_common(n * 2)]


# ---------------------------------------------------------------------------
# Bereinigung
# ---------------------------------------------------------------------------

def _clean(keywords: list[str], language: str) -> list[str]:
    """Bereinigt und dedupliziert Keywords."""
    stops = _STOPWORDS.get(language, _STOPWORDS["en"])
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        kw = kw.strip(_PUNCT_STRIP).strip()
        kw = " ".join(kw.split())
        if len(kw) < 3:
            continue
        if kw.lower() in stops:
            continue
        low = kw.lower()
        if low in seen:
            continue
        # Reine Zahlen überspringen
        if re.fullmatch(r'[\d\s.,%-]+', kw):
            continue
        # Grammatische Fragmente überspringen (Präpositionen, Artikel als erstes Wort)
        _GRAM_FRAGMENTS = {
            "des", "die", "der", "den", "dem", "das", "ein", "eine",
            "und", "oder", "von", "zu", "in", "an", "auf", "mit",
            "the", "of", "in", "on", "at", "by", "for", "and", "or",
            "du", "de", "le", "la", "les", "des", "un", "une",
        }
        first_word = kw.split()[0].lower().rstrip(".,;")
        if first_word in _GRAM_FRAGMENTS:
            continue
        seen.add(low)
        result.append(kw)

    # Multiword vor Einzelwörtern, dann nach Länge
    multi  = [k for k in result if len(k.split()) >= 2]
    single = [k for k in result if len(k.split()) == 1 and len(k) >= 4]
    return (multi + single)[:_MAX_KW_PER_SECTION]


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def extract_keywords(
    section_texts: dict[int, SectionText],
    document_language: str = "en",
) -> dict[int, SectionKeywords]:
    """
    Extrahiert Keywords für alle Abschnitte.

    Args:
        section_texts:     Ausgabe von extract_section_texts()
        document_language: Dokument-Sprache als Fallback

    Returns:
        {section_node_id: SectionKeywords}
    """
    results: dict[int, SectionKeywords] = {}

    for node_id, st in section_texts.items():
        # Sprache erkennen (pro Abschnitt)
        if st.word_count >= _MIN_WORDS_FOR_YAKE:
            lang = _detect_language(st.text)
        else:
            lang = document_language

        # Keywords extrahieren
        if st.word_count < _MIN_WORDS_FOR_YAKE:
            # Zu kurz → Titel als Keyword
            raw = [st.title] if st.title else []
            method = "title"
        else:
            raw = _yake_keywords(st.text, st.title, lang,
                                 n_keywords=_MAX_KW_PER_SECTION)
            method = "yake"

        keywords = _clean(raw, lang)

        results[node_id] = SectionKeywords(
            section_node_id=node_id,
            title=st.title,
            keywords=keywords,
            language=lang,
            method=method,
        )

        # Sprache zurückschreiben
        st.language_hint = lang

    return results
