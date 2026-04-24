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

import math
import re
import string
from collections import Counter
from dataclasses import dataclass, field

# Sprachagnostischer Token-Qualitätsfilter
# Nutzt unicode-regex wenn verfügbar (pip install regex)
try:
    import regex as _rx
    _HAS_DIGIT    = _rx.compile(r"\p{L}*\p{N}+\p{L}*")
    _BAD_REPEAT   = _rx.compile(r"(\X)\1{2,}")
    _ONLY_WORDISH = _rx.compile(r"^[\p{L}\p{M}\''\- ]+$")
    _NON_LETTER   = _rx.compile(r"[^\p{L}\p{M}]")
    _MIXED_SCRIPT = _rx.compile(
        r"[\p{Script=Latin}].*[\p{Script=Cyrillic}\p{Script=Arabic}]"
        r"|[\p{Script=Cyrillic}].*[\p{Script=Latin}]"
    )
except ImportError:
    _HAS_DIGIT    = re.compile(r"[a-zA-Z]*\d+[a-zA-Z]*")
    _BAD_REPEAT   = re.compile(r"(.)\1{2,}")
    _ONLY_WORDISH = re.compile(r"^[\w\'\-\- ]+$")
    _NON_LETTER   = re.compile(r"[^\w]")
    _MIXED_SCRIPT = re.compile(r"(?!)")

from .section_text import SectionText

import logging
logger = logging.getLogger(__name__)

_MAX_KW_PER_SECTION = 8
_MIN_WORDS_FOR_YAKE = 25

# Stopwörter pro Sprache — ergänzen YAKE's interne Listen
_FRAG_START: dict[str, set[str]] = {
    "de": {"der", "die", "das", "des", "dem", "den", "ein", "eine", "einer",
           "eines", "einem", "einen", "sche", "schen", "scher", "sches",
           "liche", "lichen", "licher", "isches", "ische", "ischen"},
    "en": {"the", "a", "an", "of", "in", "on", "at", "by", "for",
           "with", "from", "to", "and", "or", "this", "that"},
    "fr": {"le", "la", "les", "du", "des", "un", "une", "au", "aux",
           "de", "en", "par", "sur", "dans", "avec", "ce", "cette"},
    "nl": {"de", "het", "een", "van", "in", "op", "te", "en", "of"},
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "una",
           "di", "da", "in", "con", "su", "per"},
    "la": {"et", "in", "de", "ad", "ex", "cum", "per", "pro"},
}
_FRAG_END: dict[str, set[str]] = {
    "de": {"und", "oder", "aber", "auch", "nur", "noch", "wird", "wurde"},
    "en": {"and", "or", "but", "the", "a", "an", "of", "in", "is", "are"},
    "fr": {"et", "ou", "mais", "le", "la", "les", "est", "sont"},
    "nl": {"en", "of", "maar", "het", "de"},
    "it": {"e", "o", "ma", "il", "lo", "la"},
    "la": {"et", "aut", "vel", "sed"},
}


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

def _char_entropy(s: str) -> float:
    """Shannon-Entropie der Zeichen — sprachagnostisch."""
    t = s.replace(" ", "")
    if not t: return 0.0
    n = len(t)
    counts = Counter(t.lower())
    return -sum((c/n) * math.log2(c/n) for c in counts.values())


# ── Phonotaktische Sprachprofile ────────────────────────────────────────────

_LANG_PROFILES: dict[str, dict] = {
    "de": {
        "min_word_len": 4,
        "max_consonant_run": 6,
        "vowels": set("aeiouäöüyAEIOUÄÖÜY"),
        "impossible_sequences": [r"[bcdfghjklmnpqrstvwxyz]{7,}"],
        "impossible_chars": set("@#$%^&*+=|\\/<>[]{}"),
    },
    "en": {
        "min_word_len": 3,
        "max_consonant_run": 6,
        "vowels": set("aeiouAEIOU"),
        "impossible_sequences": [r"[bcdfghjklmnpqrstvwxyz]{7,}"],
        "impossible_chars": set("@#$%^&*+=|\\/<>[]{}"),
    },
    "fr": {
        "min_word_len": 2,
        "max_consonant_run": 5,
        "vowels": set("aeiouéèêëàâùûüïîœæAEIOUÉÈÊËÀÂÙÛÜÏÎŒÆ"),
        "impossible_sequences": [r"[bcdfghjklmnpqrstvwxyz]{6,}"],
        "impossible_chars": set("@#$%^&*+=|\\/<>[]{}"),
    },
    "nl": {
        "min_word_len": 3,
        "max_consonant_run": 5,
        "vowels": set("aeiouéëïóöuüAEIOUÉËÏÓÖUÜ"),
        "impossible_sequences": [r"[bcdfghjklmnpqrstvwxyz]{6,}"],
        "impossible_chars": set("@#$%^&*+=|\\/<>[]{}"),
    },
    "it": {
        "min_word_len": 3,
        "max_consonant_run": 4,
        "vowels": set("aeiouàèéìíîòóùúAEIOUÀÈÉÌÍÎÒÓÙÚ"),
        "impossible_sequences": [r"[bcdfghjklmnpqrstvwxyz]{5,}"],
        "impossible_chars": set("@#$%^&*+=|\\/<>[]{}"),
    },
    "la": {
        "min_word_len": 2,
        "max_consonant_run": 4,
        "vowels": set("aeiouAEIOU"),
        "impossible_sequences": [r"[bcdfghjklmnpqrstvwxyz]{5,}", r"[wW]"],
        "impossible_chars": set("@#$%^&*+=|\\/<>[]{}äöüÄÖÜ"),
    },
}


def _consonant_runs(word: str, vowels: set) -> int:
    max_run = current = 0
    for ch in word.lower():
        if ch.isalpha() and ch not in vowels:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def _keyword_phonotactics(kw: str, lang: str) -> bool:
    profile = _LANG_PROFILES.get(lang, _LANG_PROFILES["en"])
    for word in kw.split():
        w = word.strip()
        if not w:
            continue
        if len(w) < profile["min_word_len"]:
            return False
        if set(w) & profile["impossible_chars"]:
            return False
        for pat in profile["impossible_sequences"]:
            if re.search(pat, w, re.IGNORECASE):
                return False
        if _consonant_runs(w, profile["vowels"]) > profile["max_consonant_run"]:
            return False
        letters = [c for c in w if c.isalpha()]
        if len(letters) > 2:
            if not any(c.lower() in profile["vowels"] for c in letters):
                return False
    return True


def _token_quality(token: str) -> int:
    """
    Sprachagnostische Keyword-Qualitätsbewertung.

    Nutzt Unicode-Eigenschaften + Shannon-Entropie.
    Funktioniert für DE/EN/FR/FI/LA/NL ohne sprachspezifische Regeln.

    Score < 0  → OCR-Müll, Zahlen, Script-Mix, niedrige Entropie
    Score ≥ 0  → akzeptables Keyword
    """
    t = token.strip()
    score = 0
    if len(t) < 2:
        return -3

    if not _ONLY_WORDISH.match(t):
        score -= 2
    if _HAS_DIGIT.search(t):
        score -= 3
    if _BAD_REPEAT.search(t.casefold()):
        score -= 2
    if len(t) > 30:
        score -= 1
    if _MIXED_SCRIPT.search(t):
        score -= 3

    # Entropie: echte Wörter aller Sprachen haben ent ≥ 2.5
    ent = _char_entropy(t)
    if ent < 1.5:
        score -= 3   # "AAABBB", "9-^^"
    elif ent < 2.5:
        score -= 2   # "MTTQU"

    # Nicht-Buchstaben-Anteil (Leerzeichen ignoriert)
    t_nospace = t.replace(" ", "")
    if t_nospace:
        nlr = len(_NON_LETTER.findall(t_nospace)) / len(t_nospace)
        if nlr > 0.3:
            score -= 2

    if _ONLY_WORDISH.match(t):
        score += 1

    return score


def _clean(
    keywords: list[str],
    language: str,
    section_title: str = "",
) -> list[str]:
    """
    Bereinigt und dedupliziert Keywords.

    Filter-Pipeline:
      1. Interpunktion + Normalisierung
      2. Stoppwörter
      3. token_quality (Entropie, Unicode)
      4. Phonotaktik (sprachspezifisch)
      5. Grammatische Fragmente (sprachspezifisch)
      6. Satz-Fragmente (Kleinbuchstabe am Anfang/Ende)
      7. Layout-Artefakte (Image, Abb., Fig.)
      8. Titel-Echo
      9. Deduplizierung
    """
    stops      = _STOPWORDS.get(language, _STOPWORDS["en"])
    frag_start = _FRAG_START.get(language, _FRAG_START.get("en", set()))
    frag_end   = _FRAG_END.get(language, _FRAG_END.get("en", set()))
    title_words = set(section_title.lower().split()) if section_title else set()

    _LAYOUT = {
        "image", "images", "figure", "figures", "fig", "figs",
        "abbildung", "abb", "photo", "foto",
        "table", "tabelle", "map", "karte", "plate",
    }

    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        # 1. Normalisierung
        kw = kw.strip(_PUNCT_STRIP).strip()
        kw = " ".join(kw.split())
        if len(kw) < 3:
            continue

        words = kw.split()

        # 2. Stoppwörter
        if kw.lower() in stops:
            continue

        # 3. Token-Qualität (Entropie, Unicode, Zahlen)
        word_scores = [_token_quality(w) for w in words]
        if any(s < -1 for s in word_scores):
            continue
        if sum(word_scores) < 0:
            continue

        # Reine Zahlen/Satzzeichen
        if re.fullmatch(r'[\d\s.,%-]+', kw):
            continue

        # 4. CharLM — gelernte Sprachplausibilität (optional)
        try:
            from atlas.semantic.charlm import get_model as _get_lm
            _lm = _get_lm(language)
            if _lm is not None:
                if not all(_lm.is_plausible(w) for w in words):
                    continue
        except Exception:
            pass

        # 5. Phonotaktik
        if not _keyword_phonotactics(kw, language):
            continue



        # 6. Grammatische Fragmente (sprachspezifisch)
        first = words[0].lower().rstrip(".,;")
        last  = words[-1].lower().rstrip(".,;")
        if first in frag_start:
            continue
        if len(words) > 1 and last in frag_end:
            continue

        # 7. Satz-Fragmente: Bigramm das mit Kleinbuchstabe beginnt/endet
        if len(words) > 1:
            if words[0][0].islower() or words[-1][-1].islower():
                continue

        # 8. Layout-Artefakte
        if any(w.lower().rstrip(".,") in _LAYOUT for w in words):
            continue

        # 9. Titel-Echo: Wörter des Keywords komplett im Abschnittstitel
        if title_words and len(words) < 3:
            kw_words = set(kw.lower().split())
            if kw_words <= title_words:
                continue

        # 10. Deduplizierung
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        result.append(kw)

    # Multiword vor Einzelwörtern
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

        keywords = _clean(raw, lang, section_title=st.title or "")

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
