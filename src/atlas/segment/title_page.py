from __future__ import annotations

from atlas.segment.models import Block, Region


TITLE_PAGE_WORDS = (
    "dissertation",
    "thesis",
    "diplomarbeit",
    "masterarbeit",
    "bachelorarbeit",
    "habilitationsschrift",
    "vorgelegt",
    "erlangung des akademischen grades",
    "gutachter",
    "betreuer",
    "supervisor",
)


def _is_dense_paragraph(text: str) -> bool:
    value = " ".join((text or "").split())
    if len(value) < 350:
        return False
    sentence_punct = value.count(".") + value.count("!") + value.count("?")
    return sentence_punct >= 2


def detect_title_page(blocks: list[Block]) -> Region | None:
    if not blocks:
        return None

    page0 = [b for b in blocks if b.page_index == 0]
    if not page0:
        return None

    candidates = page0[:5]
    if not candidates:
        return None

    text = "\n\n".join(b.text for b in candidates).strip()
    if not text:
        return None

    lower = text.lower()

    score = 0
    if any(word in lower for word in TITLE_PAGE_WORDS):
        score += 2

    short_blocks = sum(1 for b in candidates if len(b.text) <= 180)
    if candidates and (short_blocks / len(candidates)) >= 0.7:
        score += 1

    dense_blocks = sum(1 for b in candidates if _is_dense_paragraph(b.text))
    if dense_blocks == 0:
        score += 1

    if score < 3:
        return None

    start_char = candidates[0].start_char
    end_char = candidates[-1].end_char

    # hard cap: title page should stay small
    if end_char - start_char > 2500:
        end_char = start_char + 2500
        text = text[:2500].strip()

    return Region(
        region_index=0,
        region_type="title_page",
        start_char=start_char,
        end_char=end_char,
        text=text,
        confidence=0.88,
        page_start=0,
        page_end=0,
    )
