from __future__ import annotations

import re

from atlas.segment.models import Block, Region


FRONT_MATTER_END_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"abstract|summary|zusammenfassung|résumé|resumé|"
    r"keywords|schlagwörter|introduction|einleitung|"
    r"inhalt|inhaltsverzeichnis|contents|table of contents"
    r")\s*:?\s*$",
    re.I,
)

SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+){0,3}\s+)?(?:einleitung|introduction|method|methods|material|results|discussion)\b",
    re.I,
)

TOC_STYLE_RE = re.compile(r"\b\d+(?:\.\d+){1,5}\b")


def _is_dense_paragraph(text: str) -> bool:
    value = " ".join((text or "").split())
    if len(value) < 420:
        return False

    sentence_punct = value.count(".") + value.count("!") + value.count("?")
    if sentence_punct < 2:
        return False

    return True


def _is_toc_like(text: str) -> bool:
    value = " ".join((text or "").split())
    if not value:
        return False

    if re.search(r"\b(?:inhalt|inhaltsverzeichnis|contents|table of contents)\b", value, re.I):
        return True

    score = 0
    if TOC_STYLE_RE.search(value):
        score += 1
    if re.search(r"(?:\s|\.)(\d{1,4})\s*$", value):
        score += 1
    if value.count(".") >= 6:
        score += 1

    return score >= 3


def detect_front_matter(blocks: list[Block]) -> Region | None:
    if not blocks:
        return None

    selected: list[Block] = []
    max_chars = 1600

    for i, block in enumerate(blocks):
        text = block.text.strip()
        if not text:
            break

        if FRONT_MATTER_END_MARKER_RE.match(text):
            break

        if _is_toc_like(text):
            break

        if SECTION_HEADING_RE.match(text):
            break

        if i >= 1 and _is_dense_paragraph(text):
            break

        selected.append(block)

        if block.end_char >= max_chars:
            break
        if len(selected) >= 5:
            break

    if not selected:
        return None

    return Region(
        region_index=0,
        region_type="front_matter",
        start_char=selected[0].start_char,
        end_char=selected[-1].end_char,
        text="\n\n".join(block.text for block in selected).strip(),
        confidence=0.80,
    )
