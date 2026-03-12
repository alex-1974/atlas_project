from __future__ import annotations

import re

from atlas.segment.models import Block, Region


REFERENCES_MARKER_RE = re.compile(
    r"^\s*(?:references|bibliography|works cited|literatur|literaturverzeichnis|bibliographie|quellen)\s*:?\s*$",
    re.I,
)

NON_REFERENCE_SECTION_RE = re.compile(
    r"^\s*(?:"
    r"einleitung|introduction|appendix|anhang|"
    r"abbildungsverzeichnis|tabellenverzeichnis|"
    r"interviews?|index|register|contents|inhaltsverzeichnis|sommaire|"
    r"kurzfassung|abstract|summary|zusammenfassung|"
    r"lebenslauf|cv|danksagung|vorwort|preface"
    r")\b",
    re.I,
)

YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}[a-z]?\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.I)
URL_RE = re.compile(r"\bhttps?://\S+\b", re.I)
PAGE_RANGE_RE = re.compile(r"\b\d+\s*[-–]\s*\d+\b")
AUTHOR_PATTERN_RE = re.compile(r"\b[A-ZÄÖÜ][a-zäöüß]+,\s*[A-Z]\.", re.U)


def _reference_like_score(text: str) -> float:
    value = " ".join((text or "").split())
    if not value:
        return 0.0

    score = 0.0

    years = len(YEAR_RE.findall(value))
    dois = len(DOI_RE.findall(value))
    urls = len(URL_RE.findall(value))
    page_ranges = len(PAGE_RANGE_RE.findall(value))
    author_forms = len(AUTHOR_PATTERN_RE.findall(value))
    commas = value.count(",")

    score += min(years * 0.8, 3.2)
    score += min(dois * 2.0, 4.0)
    score += min(urls * 1.5, 3.0)
    score += min(page_ranges * 0.8, 2.0)
    score += min(author_forms * 1.5, 3.0)
    score += min(commas / 5.0, 2.0)

    if re.search(r"\b(?:vol\.|ed\.|eds\.|pp\.|band|auflage|journal|press|verlag)\b", value, re.I):
        score += 0.8

    # punish long narrative text with weak bibliographic structure
    if len(value) > 350 and (years + dois + urls + author_forms) < 2:
        score -= 2.0

    return score


def _looks_like_reference_block(text: str) -> bool:
    return _reference_like_score(text) >= 3.6


def detect_references(blocks: list[Block], total_pages: int | None = None) -> Region | None:
    if not blocks:
        return None

    if total_pages is None:
        page_values = [b.page_index for b in blocks if b.page_index is not None]
        total_pages = (max(page_values) + 1) if page_values else 1

    late_page_threshold = max(0, int(total_pages * 0.70))
    tail_page_threshold = max(0, int(total_pages * 0.85))

    # 1) Marker-based detection: only if marker is late and followed by multiple clear reference blocks
    for i, block in enumerate(blocks):
        text = block.text.strip()
        if not REFERENCES_MARKER_RE.match(text):
            continue

        if (block.page_index or 0) < late_page_threshold:
            continue

        selected: list[Block] = []
        weak_run = 0

        for j in range(i + 1, len(blocks)):
            nxt = blocks[j]
            nxt_text = nxt.text.strip()

            if not nxt_text:
                weak_run += 1
                if weak_run >= 2 and selected:
                    break
                continue

            if NON_REFERENCE_SECTION_RE.match(nxt_text) and selected:
                break

            if _looks_like_reference_block(nxt_text):
                selected.append(nxt)
                weak_run = 0
            else:
                weak_run += 1
                if weak_run >= 2 and selected:
                    break

        if len(selected) >= 2:
            return Region(
                region_index=99,
                region_type="references",
                start_char=selected[0].start_char,
                end_char=selected[-1].end_char,
                text="\n\n".join(b.text for b in selected).strip(),
                confidence=0.94,
                page_start=selected[0].page_index,
                page_end=selected[-1].page_index,
            )

    # 2) Tail fallback: only if there are at least TWO consecutive strong blocks in the last 15% of pages
    tail_blocks = [
        b for b in blocks
        if (b.page_index or 0) >= tail_page_threshold
    ]

    if len(tail_blocks) < 2:
        return None

    best_run: list[Block] = []
    current_run: list[Block] = []

    for block in tail_blocks:
        if _looks_like_reference_block(block.text):
            current_run.append(block)
        else:
            if len(current_run) >= 2:
                if len(current_run) > len(best_run):
                    best_run = current_run[:]
            current_run = []

    if len(current_run) >= 2 and len(current_run) > len(best_run):
        best_run = current_run[:]

    if len(best_run) < 2:
        return None

    return Region(
        region_index=99,
        region_type="references",
        start_char=best_run[0].start_char,
        end_char=best_run[-1].end_char,
        text="\n\n".join(b.text for b in best_run).strip(),
        confidence=0.74,
        page_start=best_run[0].page_index,
        page_end=best_run[-1].page_index,
    )
