"""
atlas.semantic.lemma

Leichtgewichtige Lemmatisierung für Keyword-Normalisierung.
Nutzt simplemma (offline, ~500KB) ohne Modell-Downloads.

Strategie:
- simplemma für bekannte Wörter
- Kein aggressiver Suffix-Fallback (Komposita werden nicht aufgeteilt)
- Gibt Original zurück wenn simplemma nichts ändert

Unterstützte Sprachen: de, en, fr, nl, it, la (und ~30 weitere)
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

# Sprach-Mapping Atlas → simplemma
_LANG_MAP = {
    "de": "de", "en": "en", "fr": "fr",
    "nl": "nl", "it": "it", "la": "la",
}


def lemmatize(word: str, lang: str = "en") -> str:
    """Lemmatisiert ein einzelnes Wort. Fallback: Original."""
    try:
        import simplemma as _sm
        sl = _LANG_MAP.get(lang, "en")
        return _sm.lemmatize(word, lang=sl)
    except Exception:
        return word


def lemmatize_keyword(kw: str, lang: str = "en") -> str:
    """
    Lemmatisiert alle Wörter eines Keywords.
    Gibt das Original zurück wenn sich nichts ändert.
    """
    try:
        import simplemma as _sm
        sl = _LANG_MAP.get(lang, "en")
        words = kw.split()
        lemmas = [_sm.lemmatize(w, lang=sl) for w in words]
        return " ".join(lemmas)
    except Exception:
        return kw


def lemmatize_keywords(
    keywords: list[str],
    lang: str = "en",
) -> list[str]:
    """
    Lemmatisiert eine Liste von Keywords.
    Gibt Original + lemmatisierte Form zurück wenn unterschiedlich.
    Duplikate werden entfernt.
    """
    try:
        import simplemma as _sm
    except ImportError:
        logger.debug("simplemma nicht installiert — Lemmatisierung übersprungen")
        return keywords

    sl = _LANG_MAP.get(lang, "en")
    result: list[str] = []
    seen: set[str] = set()

    for kw in keywords:
        # Original
        if kw.lower() not in seen:
            seen.add(kw.lower())
            result.append(kw)

        # Lemmatisierte Form
        words  = kw.split()
        lemmas = [_sm.lemmatize(w, lang=sl) for w in words]
        lemma  = " ".join(lemmas)
        if lemma.lower() != kw.lower() and lemma.lower() not in seen:
            seen.add(lemma.lower())
            result.append(lemma)

    return result
