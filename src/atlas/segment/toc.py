from __future__ import annotations

import re

from atlas.segment.models import Block, Region


TOC_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"inhalt|inhaltsverzeichnis|contents|table of contents|sommaire"
    r")\s*:?\s*$",
    re.I,
)

SECTION_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+){1,5}\b")
TRAILING_PAGE_RE = re.compile(r"(?:\s|\.)(\d{1,4})\s*$")
ROMAN_SECTION_RE = re.compile(r"^\s*[IVXLCM]+\.\s+", re.I)
TOC_KEYWORDS_RE = re.compile(
    r"\b(?:kapitel|chapter|appendix|anhang|einleitung|introduction|"
    r"literatur|bibliographie|references|preface|vorwort|geschichte|fazit)\b",
    re.I,
)


def _normalized_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]


def _toc_score_for_line(line: str) -> int:
    score = 0
    if TOC_MARKER_RE.match(line):
        score += 5
    if SECTION_NUMBER_RE.search(line):
        score += 2
    if TRAILING_PAGE_RE.search(line):
        score += 2
    if ROMAN_SECTION_RE.search(line):
        score += 1
    if line.count(".") >= 6:
        score += 1
    if TOC_KEYWORDS_RE.search(line):
        score += 1
    return score


def _is_toc_like_block(block: Block) -> bool:
    lines = _normalized_lines(block.text)
    if not lines:
        return False

    if len(lines) == 1:
        return _toc_score_for_line(lines[0]) >= 5

    total = sum(_toc_score_for_line(line) for line in lines)
    shortish = sum(1 for line in lines if len(line) <= 140)

    if shortish >= max(2, len(lines) - 1):
        total += 1

    return total >= 6


def detect_toc(blocks: list[Block], front_matter: Region | None) -> Region | None:
    if not blocks:
        return None

    # Search from document start too, because some PDFs begin with TOC-like material.
    search_start = 0
    search_end = min(len(blocks), 18)

    best_run: tuple[int, int, int] | None = None
    run_start: int | None = None

    for i in range(search_start, search_end):
        if _is_toc_like_block(blocks[i]):
            if run_start is None:
                run_start = i
            continue

        if run_start is not None:
            run_end = i - 1
            run_len = run_end - run_start + 1
            if best_run is None or run_len > best_run[2]:
                best_run = (run_start, run_end, run_len)
            run_start = None

    if run_start is not None:
        run_end = search_end - 1
        run_len = run_end - run_start + 1
        if best_run is None or run_len > best_run[2]:
            best_run = (run_start, run_end, run_len)

    if best_run is None:
        return None

    start, end, run_len = best_run
    selected = blocks[start:end + 1]

    # Guard against false positives in mid-text narrative regions.
    if selected[0].start_char > 4000:
        return None

    # If front_matter exists and overlaps toc, trim front_matter later in document_regions.
    return Region(
        region_index=1,
        region_type="toc",
        start_char=selected[0].start_char,
        end_char=selected[-1].end_char,
        text="\n\n".join(block.text for block in selected).strip(),
        confidence=0.86 if run_len > 1 else 0.74,
    )
