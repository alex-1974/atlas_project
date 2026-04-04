# src/atlas/understanding/core/titelei_words.py
"""Multilingual titelei words for the DU pipeline.

"Titelei" refers to the front matter of a document — title page elements
that appear prominently (large font, first page) but are structural labels,
not the document title itself.

These words are used in roles.py to prevent misclassification of document
type markers and publisher elements as the document title.

Covers: English, German, French, Spanish, Swedish, Italian,
Portuguese, Dutch, Latin (common in historical documents).

Usage
-----
    from atlas.understanding.core.titelei_words import TITELEI_WORDS

    if text.strip().lower() in TITELEI_WORDS:
        # suppress title_score

All entries are lowercase, whitespace-normalised, single tokens or
short fixed phrases only. Do NOT add section headings here
(e.g. "introduction", "summary") — those belong in section_labels.py.

Rule of thumb: a word belongs here if and only if it would be bizarre
as a document title. "Impressum" is never a title. "Introduction" often is.
"""
from __future__ import annotations


TITELEI_WORDS: frozenset[str] = frozenset({

    # ── Document type labels ──────────────────────────────────────────────────
    # These appear on title pages to label the document kind, not as titles.

    # German academic
    "diplomarbeit", "magisterarbeit", "masterarbeit", "bachelorarbeit",
    "doktorarbeit", "habilitationsschrift", "inaugural-dissertation",
    "seminararbeit", "hausarbeit", "projektarbeit", "studienarbeit",

    # English academic
    "dissertation", "thesis",

    # French academic
    "mémoire", "thèse", "rapport de stage",

    # ── Publisher / series structural labels ──────────────────────────────────

    # German
    "impressum", "herausgeber", "herausgegeben von",
    "verlag", "schriftenreihe", "reihe",
    "widmung", "danksagung",
    "inhaltsverzeichnis", "inhaltsübersicht",
    "abbildungsverzeichnis", "tabellenverzeichnis",
    "abkürzungsverzeichnis",

    # English
    "imprint", "dedication", "acknowledgements", "acknowledgments",
    "table of contents", "list of figures", "list of tables",
    "list of abbreviations", "edited by", "compiled by",
    "foreword", "copyright",

    # French
    "avant-propos", "dédicace", "remerciements",
    "table des matières", "liste des figures",
    "droits d'auteur",

    # Spanish
    "dedicatoria", "agradecimientos",
    "tabla de contenidos", "índice",

    # Swedish
    "förord", "innehållsförteckning", "tack",

    # Italian
    "dedica", "ringraziamenti", "indice",

    # Dutch
    "voorwoord", "inhoudsopgave", "dankwoord",

    # ── Series / volume markers ───────────────────────────────────────────────
    # Single tokens that label a volume/part, not a title.
    # Note: "band", "teil", "part", "volume", "heft" are excluded because
    # they commonly appear in legitimate titles ("Band 3 der Schriftenreihe").

    # ── Publisher imprint lines ───────────────────────────────────────────────
    "verfasst von", "bearbeitet von", "eingereicht von",
    "submitted to", "in partial fulfillment", "zur erlangung",
    "for the degree of", "für den studiengang",

})
