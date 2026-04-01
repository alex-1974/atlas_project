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
    "thesis", "dissertation", "doctoral thesis", "doctoral dissertation",
    "phd thesis", "ph.d.", "doctor of philosophy",
    "master thesis", "masterarbeit", "diplomarbeit", "doktorarbeit",
    "habilitationsschrift", "submitted to", "in partial fulfillment",
    "for the degree of", "zur erlangung", "inaugural-dissertation",
)
_UNIVERSITY = (
    "university", "faculty", "department", "school of", "college of",
    "graduate school", "universität", "fakultät", "institut für",
    "department of",
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
    blocks: list[dict], limit: int = 10
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

    return {
        "journal_meta_count":        journal,
        "doi_count":                 doi,
        "thesis_marker_count":       thesis,
        "university_marker_count":   university,
        "report_marker_count":       report,
        "short_line_count":          short,
        "strong_journal_header":     bool(doi >= 1 and journal >= 1),
        "very_strong_journal_header": bool(doi >= 1 and journal >= 2),
        "strong_thesis_header":      bool(
            thesis >= 1
            or (university >= 1 and doi == 0 and journal == 0)
        ),
    }
