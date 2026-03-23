from __future__ import annotations


JOURNAL_META_MARKERS = (
    "journal",
    "vol.",
    "volume",
    "issue",
    "pp.",
    "pages",
    "issn",
    "transactions of",
    "proceedings of",
    "vernacular architecture",
)

DOI_MARKERS = (
    "doi:",
    "doi.org/",
    "https://doi.org/",
    "http://doi.org/",
)

THESIS_MARKERS = (
    "thesis",
    "dissertation",
    "doctoral thesis",
    "doctoral dissertation",
    "phd thesis",
    "ph.d.",
    "doctor of philosophy",
    "master thesis",
    "masterarbeit",
    "diplomarbeit",
    "doktorarbeit",
    "habilitationsschrift",
    "submitted to",
    "in partial fulfillment",
    "for the degree of",
    "zur erlangung",
    "inaugural-dissertation",
)

UNIVERSITY_MARKERS = (
    "university",
    "faculty",
    "department",
    "school of",
    "college of",
    "graduate school",
    "universität",
    "fakultät",
    "institut für",
    "department of",
)

REPORT_MARKERS = (
    "report",
    "guidance",
    "guideline",
    "white paper",
    "working paper",
    "technical report",
    "research report",
)


def _norm(text: str | None) -> str:
    return " ".join((text or "").strip().split()).lower()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _early_block_texts(blocks: list[dict], limit: int = 10) -> list[str]:
    out: list[str] = []
    for block in blocks[:limit]:
        text = (block.get("text") or "").strip()
        if text:
            out.append(text)
    return out


def detect_early_meta_signals(blocks: list[dict], limit: int = 10) -> dict[str, int | bool]:
    texts = _early_block_texts(blocks, limit=limit)

    journal_meta_count = 0
    doi_count = 0
    thesis_marker_count = 0
    university_marker_count = 0
    report_marker_count = 0
    short_line_count = 0

    for text in texts:
        low = _norm(text)

        if _contains_any(low, JOURNAL_META_MARKERS):
            journal_meta_count += 1

        if _contains_any(low, DOI_MARKERS):
            doi_count += 1

        if _contains_any(low, THESIS_MARKERS):
            thesis_marker_count += 1

        if _contains_any(low, UNIVERSITY_MARKERS):
            university_marker_count += 1

        if _contains_any(low, REPORT_MARKERS):
            report_marker_count += 1

        if len(text.split()) <= 14:
            short_line_count += 1

    strong_journal_header = bool(
        doi_count >= 1
        and journal_meta_count >= 1
    )
    very_strong_journal_header = bool(
        doi_count >= 1
        and journal_meta_count >= 2
    )
    strong_thesis_header = bool(
        thesis_marker_count >= 1
        or (university_marker_count >= 1 and doi_count == 0 and journal_meta_count == 0)
    )

    return {
        "journal_meta_count": journal_meta_count,
        "doi_count": doi_count,
        "thesis_marker_count": thesis_marker_count,
        "university_marker_count": university_marker_count,
        "report_marker_count": report_marker_count,
        "short_line_count": short_line_count,
        "strong_journal_header": strong_journal_header,
        "very_strong_journal_header": very_strong_journal_header,
        "strong_thesis_header": strong_thesis_header,
    }
