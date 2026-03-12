from __future__ import annotations

import re

from atlas.segment.models import Block, Region


ABSTRACT_MARKER_RE = re.compile(
    r"^\s*(?:abstract|summary|zusammenfassung|résumé|resumé)\s*:?\s*$",
    re.I,
)

NEXT_SECTION_RE = re.compile(
    r"^\s*(?:"
    r"keywords|schlagwörter|introduction|einleitung|"
    r"references|bibliography|works cited|literatur|literaturverzeichnis|bibliographie|"
    r"inhalt|inhaltsverzeichnis|contents|table of contents"
    r")\s*:?\s*$",
    re.I,
)

INTRO_LIKE_RE = re.compile(r"^\s*(?:\d+(?:\.\d+){0,3}\s+)?(?:einleitung|introduction)\b", re.I)


def _is_dense_paragraph(text: str) -> bool:
    value = " ".join((text or "").split())
    if len(value) < 350:
        return False
    sentence_punct = value.count(".") + value.count("!") + value.count("?")
    return sentence_punct >= 2


def detect_abstract(
    blocks: list[Block],
    front_matter: Region | None,
    toc_region: Region | None = None,
) -> Region | None:
    if not blocks:
        return None

    search_start_char = 0
    if toc_region is not None:
        search_start_char = toc_region.end_char
    elif front_matter is not None:
        search_start_char = front_matter.end_char

    start_idx = 0
    for i, block in enumerate(blocks):
        if block.start_char >= search_start_char:
            start_idx = i
            break

    for i in range(start_idx, min(len(blocks), start_idx + 8)):
        text = blocks[i].text.strip()
        if not ABSTRACT_MARKER_RE.match(text):
            continue

        selected: list[Block] = []
        for j in range(i + 1, len(blocks)):
            nxt = blocks[j]
            nxt_text = nxt.text.strip()

            if NEXT_SECTION_RE.match(nxt_text) or INTRO_LIKE_RE.match(nxt_text):
                break

            if len(selected) >= 1 and not _is_dense_paragraph(nxt_text):
                break

            selected.append(nxt)

            if sum(len(b.text) for b in selected) >= 2500:
                break

        if selected:
            return Region(
                region_index=2,
                region_type="abstract_or_summary",
                start_char=selected[0].start_char,
                end_char=selected[-1].end_char,
                text="\n\n".join(block.text for block in selected).strip(),
                confidence=0.95,
            )

    for i in range(start_idx, min(len(blocks), start_idx + 3)):
        text = blocks[i].text.strip()
        if INTRO_LIKE_RE.match(text):
            break

        if _is_dense_paragraph(text):
            return Region(
                region_index=2,
                region_type="abstract_or_summary",
                start_char=blocks[i].start_char,
                end_char=blocks[i].end_char,
                text=blocks[i].text.strip(),
                confidence=0.42,
            )

    return None
