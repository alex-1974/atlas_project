# src/atlas/understanding/interpret/early_meta.py
"""Scan the first N blocks for document-type signals.

Used by roles.py, zones.py, and section_tree.py to adjust their
behaviour based on whether the document looks like a journal article,
thesis, or report.

The key 'strong_journal_header' is the canonical name — roles.py in
the old system incorrectly queried 'has_journal_meta' (Bug 2).
"""
from __future__ import annotations


_JOURNAL_META = (
    "journal", "vol.", "volume", "issue", "pp.", "pages", "issn",
    "transactions of", "proceedings of", "vernacular architecture",
)
_DOI = (
    "doi:", "doi.org/", "https://doi.org/", "http://doi.org/",
)
_THESIS = (
    # Explicit document type labels (highest confidence)
    "thesis", "dissertation", "doctoral thesis", "doctoral dissertation",
    "phd thesis", "ph.d.", "doctor of philosophy",
    "master thesis", "masterarbeit", "diplomarbeit", "magisterarbeit",
    "doktorarbeit", "habilitationsschrift", "inaugural-dissertation",
    "mémoire", "thèse", "proefschrift", "tesi di dottorato",
    "tesi di laurea", "masterscriptie",
    # Degree-conferral statements (universal across institutions/languages)
    "in partial fulfillment", "submitted in partial",
    "for the degree of", "for the requirements of",
    "zur erlangung", "zur erlangung des grades",
    "zur erlangung der würde", "zur erlangung des akademischen",
    "pour l'obtention", "pour l'obtention du grade",
    "ter verkrijging van de graad",
    # Supervisor/committee markers (only appear in theses)
    "betreuer:", "erstbetreuer:", "zweitbetreuer:",
    "erstgutachter:", "zweitgutachter:", "gutachter:",
    "supervisor:", "co-supervisor:", "thesis advisor:",
    "dissertation advisor:", "committee chair:",
    "directeur de thèse:", "promotor:",
    "approved by:", "submitted to",
)
_UNIVERSITY = (
    "university", "faculty", "department", "school of", "college of",
    "graduate school", "universität", "fakultät", "institut für",
    "department of",
)

# Supervisor/committee markers — subset of _THESIS for targeted use
_SUPERVISOR = (
    "betreuer", "gutachter", "supervisor", "committee chair",
    "directeur de thèse", "promotor", "approved by",
    "dissertation advisor", "thesis advisor",
)
_REPORT = (
    "report", "guidance", "guideline", "white paper",
    "working paper", "technical report", "research report",
)


def _norm(text: str | None) -> str:
    return " ".join((text or "").strip().split()).lower()


def _has(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def detect_early_meta_signals(
    blocks: list[dict], limit: int = 6
) -> dict[str, int | bool]:
    """Return document-type signals derived from the first `limit` blocks.

    Keys
    ----
    journal_meta_count, doi_count, thesis_marker_count,
    university_marker_count, report_marker_count, short_line_count,
    strong_journal_header, very_strong_journal_header, strong_thesis_header
    """
    journal = doi = thesis = university = report = short = 0

    for block in blocks[:limit]:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        low = _norm(text)
        if _has(low, _JOURNAL_META):  journal   += 1
        if _has(low, _DOI):           doi       += 1
        if _has(low, _THESIS):        thesis    += 1
        if _has(low, _UNIVERSITY):    university += 1
        if _has(low, _REPORT):        report    += 1
        if len(text.split()) <= 14:   short     += 1

    # Count supervisor/committee markers separately for thesis detection
    supervisor = sum(
        1 for block in blocks[:limit]
        for needle in _SUPERVISOR
        if needle in _norm(block.get("text") or "")
    )

    return {
        "journal_meta_count":        journal,
        "doi_count":                 doi,
        "thesis_marker_count":       thesis,
        "university_marker_count":   university,
        "supervisor_marker_count":   supervisor,
        "report_marker_count":       report,
        "short_line_count":          short,
        "strong_journal_header":     bool(doi >= 1 and journal >= 1),
        "very_strong_journal_header": bool(doi >= 1 and journal >= 2),
        # strong_thesis_header requires explicit evidence:
        # - an explicit thesis type label or degree-conferral statement, OR
        # - a supervisor/committee marker (only appears in theses), OR
        # - university >= 2 AND no journal/DOI signals (weak fallback)
        "strong_thesis_header":      bool(
            thesis >= 1
            or supervisor >= 1
            or (university >= 2 and doi == 0 and journal == 0)
        ),
    }
