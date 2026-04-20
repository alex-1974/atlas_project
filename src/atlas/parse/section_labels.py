# src/atlas/parse/section_labels.py
"""Multilingual section heading labels for atlas.parse.

Single source of truth for all language-specific section names.
Covers: English, German, French, Spanish, Swedish, Italian,
Portuguese, Dutch, Latin (common in historical documents).

Usage
-----
    from atlas.parse.section_labels import (
        ABSTRACT_HEADINGS, BODY_START_HEADINGS, REFERENCE_HEADINGS, ...
    )
    if normalize_lower(text) in BODY_START_HEADINGS: ...

All sets contain lowercase, whitespace-normalised forms only.
Regex patterns are derived from the sets so there is exactly one
place to add new terms or languages.

Zone logic
----------
Frontmatter ends / Body begins at the first block matching
BODY_START_HEADINGS — or at the first block that is typographically
body-like and follows no FRONTMATTER_HEADINGS on that page.

Backmatter begins at the first block matching ALL_BACK_MATTER_HEADINGS.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _make_re(headings: frozenset[str]) -> re.Pattern:
    """Build a start-anchored, case-insensitive pattern from a heading set."""
    alts = "|".join(re.escape(s) for s in sorted(headings, key=len, reverse=True))
    return re.compile(r"^\s*(" + alts + r")\s*[:\.\-]?\s*$", re.IGNORECASE)


def _make_prefix_re(headings: frozenset[str]) -> re.Pattern:
    """Build a start-anchored prefix pattern (text may follow on same line)."""
    alts = "|".join(re.escape(s) for s in sorted(headings, key=len, reverse=True))
    return re.compile(r"^\s*(" + alts + r")\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# References / Bibliography  →  Backmatter anchor
# ---------------------------------------------------------------------------

REFERENCE_HEADINGS: frozenset[str] = frozenset({
    # English
    "references", "bibliography", "works cited", "literature cited",
    "reference list", "cited works", "cited literature",
    # German
    "literatur", "literaturverzeichnis", "quellen", "quellenverzeichnis",
    "schrifttum", "bibliografie", "bibliographie",
    # French
    "références", "bibliographie", "ouvrages cités",
    "liste des références", "liste bibliographique",
    # Spanish
    "referencias", "bibliografía", "obras citadas",
    "lista de referencias",
    # Swedish
    "referenser", "litteraturförteckning", "källförteckning",
    # Italian
    "riferimenti", "bibliografia", "opere citate",
    # Portuguese
    "referências", "bibliografia", "obras citadas",
    # Dutch
    "literatuur", "referenties", "bronnen", "bibliografie",
    # Latin (historical)
    "bibliographia",
})

REFERENCES_RE: re.Pattern = _make_re(REFERENCE_HEADINGS)


# ---------------------------------------------------------------------------
# Abstract / Summary  →  Frontmatter anchor (signals end of pure title pages)
# ---------------------------------------------------------------------------

ABSTRACT_HEADINGS: frozenset[str] = frozenset({
    # English
    "abstract", "summary", "synopsis", "executive summary",
    # German
    "zusammenfassung", "kurzfassung", "kurzreferat", "resümee",
    "abstrakt",
    # French
    "résumé", "sommaire", "abrégé",
    # Spanish
    "resumen", "sumario", "sinopsis",
    # Swedish
    "sammanfattning", "abstrakt",
    # Italian
    "sommario", "riassunto", "estratto",
    # Portuguese
    "resumo", "sumário",
    # Dutch
    "samenvatting", "overzicht",
})

ABSTRACT_RE: re.Pattern = _make_re(ABSTRACT_HEADINGS)


# ---------------------------------------------------------------------------
# Keywords  →  Frontmatter anchor
# ---------------------------------------------------------------------------

KEYWORDS_HEADINGS: frozenset[str] = frozenset({
    # English
    "keywords", "key words", "index terms", "subject terms",
    # German
    "schlagwörter", "schlagworte", "stichwörter",
    "schlüsselwörter", "schlüsselbegriffe",
    # French
    "mots-clés", "mots clés",
    # Spanish
    "palabras clave",
    # Swedish
    "nyckelord",
    # Italian
    "parole chiave",
    # Portuguese
    "palavras-chave",
    # Dutch
    "trefwoorden", "sleutelwoorden",
})

KEYWORDS_RE: re.Pattern = _make_re(KEYWORDS_HEADINGS)


# ---------------------------------------------------------------------------
# Appendix  →  Backmatter anchor
# ---------------------------------------------------------------------------

APPENDIX_HEADINGS: frozenset[str] = frozenset({
    # English
    "appendix", "appendices", "annex", "annexes",
    # German
    "anhang", "anhänge", "anlage", "anlagen",
    # French
    "annexe", "annexes",
    # Spanish
    "apéndice", "apéndices", "anexo", "anexos",
    # Swedish
    "bilaga", "bilagor",
    # Italian
    "appendice", "appendici",
    # Portuguese
    "apêndice", "apêndices", "anexo",
    # Dutch
    "bijlage", "bijlagen",
})

APPENDIX_RE: re.Pattern = _make_re(APPENDIX_HEADINGS)


# ---------------------------------------------------------------------------
# Table of Contents  →  Frontmatter anchor
# ---------------------------------------------------------------------------

TOC_HEADINGS: frozenset[str] = frozenset({
    # English
    "contents", "table of contents",
    # German
    "inhaltsverzeichnis", "inhalt",
    # French
    "table des matières", "sommaire",
    # Spanish
    "índice", "tabla de contenidos",
    # Swedish
    "innehållsförteckning", "innehåll",
    # Italian
    "indice", "sommario",
    # Portuguese
    "índice", "sumário",
    # Dutch
    "inhoudsopgave", "inhoud",
})

TOC_RE: re.Pattern = _make_re(TOC_HEADINGS)


# ---------------------------------------------------------------------------
# Frontmatter headings  →  signals still-in-frontmatter
# ---------------------------------------------------------------------------

FRONTMATTER_HEADINGS: frozenset[str] = frozenset({
    # Preface / Foreword
    "preface", "foreword",
    # German
    "vorwort", "geleitwort", "vorbemerkung", "vorbemerkungen",
    "vorrede",
    # French
    "préface", "avant-propos", "avertissement",
    # Spanish
    "prefacio", "prólogo",
    # Swedish
    "förord",
    # Italian
    "prefazione", "premessa",
    # Portuguese
    "prefácio",
    # Dutch
    "voorwoord",

    # Acknowledgements
    "acknowledgements", "acknowledgments",
    # German
    "danksagung", "dank",
    # French
    "remerciements",
    # Spanish
    "agradecimientos",
    # Italian
    "ringraziamenti",
    # Portuguese
    "agradecimentos",
    # Dutch
    "dankwoord",

    # Dedication
    "dedication",
    # German
    "widmung",
    # French
    "dédicace",
    # Spanish
    "dedicatoria",
    # Italian
    "dedica",
    # Portuguese
    "dedicatória",

    # Imprint / Colophon
    "imprint", "colophon", "impressum",
    # French
    "colophon",

    # Editorial note
    "editorial note", "editor's note", "note to the reader",
    # German
    "editorische notiz", "anmerkung der redaktion",
    # French
    "note éditoriale", "note de l'éditeur",

    # List of abbreviations (frontmatter variant)
    "abbreviations", "list of abbreviations",
    # German
    "abkürzungen", "abkürzungsverzeichnis",
    # French
    "abréviations", "liste des abréviations",
    # Dutch
    "afkortingen",
}) | TOC_HEADINGS | ABSTRACT_HEADINGS | KEYWORDS_HEADINGS

FRONTMATTER_RE: re.Pattern = _make_re(FRONTMATTER_HEADINGS)


# ---------------------------------------------------------------------------
# Body-start headings  →  strong signal that body has begun
#
# These are the most reliable anchors: a numbered first chapter or
# "Introduction" / "Einleitung" almost always marks the content start.
# Matched case-insensitively; optional leading chapter number handled
# by BODY_START_NUMBERED_RE below.
# ---------------------------------------------------------------------------

BODY_START_HEADINGS: frozenset[str] = frozenset({
    # English
    "introduction", "background", "overview",
    "motivation", "problem statement",
    # German
    "einleitung", "einführung", "hintergrund", "überblick",
    "problemstellung", "fragestellung",
    # French
    "introduction", "contexte", "présentation",
    # Spanish
    "introducción", "antecedentes",
    # Swedish
    "inledning", "bakgrund",
    # Italian
    "introduzione", "contesto",
    # Portuguese
    "introdução", "contexto",
    # Dutch
    "inleiding", "achtergrond",
})

BODY_START_RE: re.Pattern = _make_re(BODY_START_HEADINGS)

# Matches "1.", "Chapter 1", "Kapitel 1", "I. Title" at line start.
# Strict to avoid footnote numbers ("14 Ibid."), abbreviations ("5 Abb."),
# and TOC entries ("10<tab>Title").
# Plain "N Word": unicode capital + >= 4 more \w chars (= word >= 5 total).
BODY_START_NUMBERED_RE: re.Pattern = re.compile(
    r"^\s*(?:"
    # named: Chapter 1, Kapitel 2, Chapitre 3
    r"(?i:chapter|kapitel|chapitre|capitolo|cap[\u00ed]tulo|hoofdstuk)\s+\d"
    # roman: I. II. IV. + word >= 3 chars
    r"|[IVX]{1,4}[.]\s+\w{3,}"
    # arabic + dot: 1. 2. + word >= 3 chars
    r"|\d+[.]\s+\w{3,}"
    # plain arabic: "1 Einleitung" — space only, capital + >= 4 more = word >= 5
    r"|\d+[ ]+[\u00c0-\u024fA-Z]\w{4,}"
    r")"
)



# ---------------------------------------------------------------------------
# Additional backmatter headings  →  signals backmatter has begun
# ---------------------------------------------------------------------------

BACKMATTER_HEADINGS: frozenset[str] = frozenset({
    # Index
    "index", "subject index", "author index", "name index",
    # German
    "register", "sachregister", "personenregister", "ortsregister",
    "namenregister", "stichwortverzeichnis",
    # French
    "index", "index des auteurs", "index des matières",
    # Spanish
    "índice analítico",
    # Italian
    "indice analitico",
    # Dutch
    "register", "zaakregister",

    # Glossary
    "glossary", "glossaries",
    # German
    "glossar",
    # French
    "glossaire",
    # Spanish
    "glosario",
    # Italian
    "glossario",
    # Portuguese
    "glossário",
    # Dutch
    "woordenlijst",

    # List of figures / tables / illustrations
    "list of figures", "list of illustrations", "list of tables",
    "list of plates",
    # German
    "abbildungsverzeichnis", "tabellenverzeichnis",
    "abkürzungsverzeichnis",
    # French
    "liste des figures", "liste des tableaux", "liste des illustrations",
    # Dutch
    "lijst van figuren", "lijst van tabellen",

    # Colophon (backmatter variant in books)
    "colophon",
}) | REFERENCE_HEADINGS | APPENDIX_HEADINGS

BACKMATTER_RE: re.Pattern = _make_re(BACKMATTER_HEADINGS)


# ---------------------------------------------------------------------------
# Figure / Table caption prefixes
# ---------------------------------------------------------------------------

FIGURE_PREFIXES: frozenset[str] = frozenset({
    "figure", "fig.", "fig ",
    "abbildung", "abb.",
    "figure", "fig.",
    "figura", "fig.",
    "figur",
    "figuur", "afbeelding",
    "tafel",          # historical German
    "plate",          # archival English
})

TABLE_PREFIXES: frozenset[str] = frozenset({
    "table",
    "tabelle", "tab.",
    "tableau",
    "tabla", "cuadro",
    "tabell",
    "tabella",
    "tabela",
    "tabel",
    "tab.",
})

FIGURE_RE: re.Pattern = _make_prefix_re(FIGURE_PREFIXES)
TABLE_RE: re.Pattern  = _make_prefix_re(TABLE_PREFIXES)


# ---------------------------------------------------------------------------
# Convenience aggregates
# ---------------------------------------------------------------------------

ALL_FRONTMATTER_HEADINGS: frozenset[str] = FRONTMATTER_HEADINGS

ALL_BODY_START_HEADINGS: frozenset[str] = BODY_START_HEADINGS

ALL_BACK_MATTER_HEADINGS: frozenset[str] = BACKMATTER_HEADINGS
