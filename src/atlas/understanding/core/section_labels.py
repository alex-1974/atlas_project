# src/atlas/understanding/core/section_labels.py
"""Multilingual section heading labels for the DU pipeline.

Single source of truth for all language-specific section names.
Covers: English, German, French, Spanish, Swedish, Italian,
Portuguese, Dutch, Latin (common in historical documents).

Usage
-----
    from atlas.understanding.core.section_labels import (
        REFERENCE_HEADINGS, ABSTRACT_HEADINGS, ...
    )
    if normalize_lower(text) in REFERENCE_HEADINGS: ...

All sets contain lowercase, whitespace-normalised forms only.
Regex patterns for semantic_micro.py are derived here as well
so there is exactly one place to add new languages.
"""
from __future__ import annotations

import re


# ── References / Bibliography ─────────────────────────────────────────────────

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

# Regex for semantic_micro.py (matches at line start)
REFERENCES_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(REFERENCE_HEADINGS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ── Abstract / Summary ────────────────────────────────────────────────────────

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

ABSTRACT_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(ABSTRACT_HEADINGS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ── Keywords ──────────────────────────────────────────────────────────────────

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

KEYWORDS_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(KEYWORDS_HEADINGS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ── Appendix ──────────────────────────────────────────────────────────────────

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

APPENDIX_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(APPENDIX_HEADINGS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ── Table of Contents ─────────────────────────────────────────────────────────

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

TOC_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(TOC_HEADINGS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ── Figure / Table markers (for caption detection) ────────────────────────────

FIGURE_PREFIXES: frozenset[str] = frozenset({
    # English
    "figure", "fig.", "fig ",
    # German
    "abbildung", "abb.",
    # French
    "figure", "fig.",
    # Spanish
    "figura", "fig.",
    # Swedish
    "figur",
    # Italian
    "figura",
    # Portuguese
    "figura",
    # Dutch
    "figuur", "afbeelding",
})

TABLE_PREFIXES: frozenset[str] = frozenset({
    # English
    "table",
    # German
    "tabelle", "tab.",
    # French
    "tableau",
    # Spanish
    "tabla", "cuadro",
    # Swedish
    "tabell",
    # Italian
    "tabella",
    # Portuguese
    "tabela",
    # Dutch
    "tabel",
    # Shared short form
    "tab.",
})

FIGURE_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(FIGURE_PREFIXES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

TABLE_RE: re.Pattern = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in sorted(TABLE_PREFIXES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ── Convenience: all structural anchor headings ───────────────────────────────

ALL_BACK_MATTER_HEADINGS: frozenset[str] = REFERENCE_HEADINGS | APPENDIX_HEADINGS
