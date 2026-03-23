# -----------------------------------------------------------------------------
# LEGACY HEADING HEURISTICS
#
# This module is retained for older segmentation/structure workflows.
# It is NOT the canonical heading detection logic for the current DU pipeline.
#
# Canonical implementation:
#   atlas.document_understanding.core.heading
# -----------------------------------------------------------------------------

from __future__ import annotations

import re

from atlas.segment.models import Block


REGION_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"abstract|summary|zusammenfassung|résumé|resumé|"
    r"references|bibliography|works cited|literatur|literaturverzeichnis|bibliographie|"
    r"keywords|schlagwörter|einleitung|introduction|inhalt|contents|table of contents|sommaire|"
    r"appendix|anhang"
    r")\s*:?\s*$",
    re.I,
)

NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+){0,4}|[A-Z]|[IVXLCM]+)[\.\)]?\s+[^\s].*$"
)

LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.\)])\s+")
TOC_DOTS_RE = re.compile(r"\.{3,}")
TRAILING_PAGE_RE = re.compile(r"(?:\s|\.)(\d{1,4})\s*$")
EMAIL_RE = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.I)

SENTENCE_HINT_WORDS = {
    "the", "and", "with", "from", "that", "this", "these", "those",
    "are", "is", "was", "were", "be", "been", "being",
    "der", "die", "das", "und", "mit", "von", "ein", "eine", "einer",
    "ist", "sind", "war", "waren", "dies", "diese", "dieser", "dieses",
}

AUTHORISH_LINE_RE = re.compile(
    r"^(?:"
    r"[A-ZÀ-ÖØ-Ý]\.\s*"
    r"){1,3}[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+$"
    r"|^"
    r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+"
    r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+){1,3}$"
)

LOWER_CONNECTORS = {
    "de", "del", "der", "den", "van", "von", "zu", "zum", "zur",
    "la", "le", "du", "des", "da", "dos", "di", "of", "and",
    "und", "et", "y", "della", "delle", "dei",
}


def is_blank_line(line: str) -> bool:
    return not (line or "").strip()


def _normalize_inline_whitespace(text: str) -> str:
    return " ".join((text or "").strip().split())


def line_word_count(line: str) -> int:
    return len(_normalize_inline_whitespace(line).split())


def is_region_marker(line: str) -> bool:
    return bool(REGION_MARKER_RE.match((line or "").strip()))


def is_toc_like_line(line: str) -> bool:
    value = _normalize_inline_whitespace(line)
    if not value:
        return False

    score = 0
    if TOC_DOTS_RE.search(value):
        score += 1
    if TRAILING_PAGE_RE.search(value):
        score += 1
    if re.search(r"\b(?:contents|inhalt|inhaltsverzeichnis|table of contents|sommaire)\b", value, re.I):
        score += 2

    return score >= 2


def is_list_like_line(line: str) -> bool:
    value = _normalize_inline_whitespace(line)
    if not value:
        return False
    return bool(LIST_MARKER_RE.match(value))


def is_metadata_like_line(line: str) -> bool:
    value = _normalize_inline_whitespace(line)
    if not value:
        return False

    if EMAIL_RE.search(value):
        return True

    if len(value) > 120:
        return False

    words = value.split()
    if not (1 <= len(words) <= 6):
        return False

    if AUTHORISH_LINE_RE.match(value):
        return True

    # Mostly titlecase / initials without sentence character.
    alpha_words = []
    for word in words:
        cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ.'`\-]", "", word)
        if not cleaned:
            continue
        alpha_words.append(cleaned)

    if not alpha_words:
        return False

    good = 0
    for token in alpha_words:
        low = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", token).casefold()
        if low in LOWER_CONNECTORS:
            good += 1
            continue
        if re.fullmatch(r"[A-ZÀ-ÖØ-Ý]\.", token):
            good += 1
            continue
        if token[:1].isupper():
            good += 1

    return good >= max(2, len(alpha_words) - 1)


def is_heading_like_line(line: str) -> bool:
    value = _normalize_inline_whitespace(line)
    if not value:
        return False

    if is_region_marker(value):
        return True

    if is_toc_like_line(value):
        return False

    if is_list_like_line(value):
        return False

    if NUMBERED_HEADING_RE.match(value):
        return True

    if len(value) > 120:
        return False

    if value.endswith("."):
        return False

    if "," in value or ";" in value:
        return False

    words = value.split()
    if not (1 <= len(words) <= 10):
        return False

    lower_words = {re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", w).casefold() for w in words}
    lower_words.discard("")
    if lower_words & SENTENCE_HINT_WORDS:
        return False

    alpha = 0
    uppercase = 0
    for ch in value:
        if ch.isalpha():
            alpha += 1
            if ch.isupper():
                uppercase += 1

    if alpha == 0:
        return False

    ratio = uppercase / alpha
    return ratio >= 0.22


def _normalize_block_text(lines: list[str]) -> str:
    text = "".join(lines).replace("\x00", "")
    norm_lines = [" ".join(line.rstrip("\n").split()) for line in text.splitlines()]
    text = "\n".join(norm_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def merge_adjacent_heading_blocks(blocks: list[Block]) -> list[Block]:
    if not blocks:
        return []

    merged: list[Block] = []
    i = 0
    n = len(blocks)

    while i < n:
        current = blocks[i]

        if i + 1 < n:
            nxt = blocks[i + 1]
            if (
                current.page_index == nxt.page_index
                and len(current.text) <= 120
                and len(nxt.text) <= 120
                and is_heading_like_line(current.text)
                and is_heading_like_line(nxt.text)
                and not is_region_marker(current.text)
                and not is_region_marker(nxt.text)
            ):
                merged.append(
                    Block(
                        block_index=0,
                        start_char=current.start_char,
                        end_char=nxt.end_char,
                        text=f"{current.text} {nxt.text}".strip(),
                        page_index=current.page_index,
                    )
                )
                i += 2
                continue

        merged.append(current)
        i += 1

    return [
        Block(
            block_index=i,
            start_char=block.start_char,
            end_char=block.end_char,
            text=block.text,
            page_index=block.page_index,
        )
        for i, block in enumerate(merged)
    ]


def _segment_single_page(page_index: int, page_start: int, page_text: str) -> list[Block]:
    if not page_text:
        return []

    text = page_text.replace("\x00", "")
    lines = text.splitlines(keepends=True)

    blocks: list[Block] = []
    current_lines: list[str] = []
    current_start: int | None = None
    offset = 0

    def flush(end_offset: int) -> None:
        nonlocal current_lines, current_start

        if current_start is None:
            current_lines = []
            return

        block_text = _normalize_block_text(current_lines)
        if block_text:
            blocks.append(
                Block(
                    block_index=len(blocks),
                    start_char=page_start + current_start,
                    end_char=page_start + end_offset,
                    text=block_text,
                    page_index=page_index,
                )
            )

        current_lines = []
        current_start = None

    for idx, raw_line in enumerate(lines):
        line_start = offset
        line_end = offset + len(raw_line)
        stripped = _normalize_inline_whitespace(raw_line)

        if not stripped:
            flush(line_start)
            offset = line_end
            continue

        current_is_marker = is_region_marker(stripped)
        current_is_heading = is_heading_like_line(stripped)
        current_is_meta = is_metadata_like_line(stripped)
        current_is_list = is_list_like_line(stripped)
        current_is_toc = is_toc_like_line(stripped)

        next_line = ""
        if idx + 1 < len(lines):
            next_line = _normalize_inline_whitespace(lines[idx + 1])

        next_is_marker = is_region_marker(next_line) if next_line else False
        next_is_heading = is_heading_like_line(next_line) if next_line else False

        # Structural single-line blocks always stand on their own.
        if current_is_marker or current_is_toc or current_is_heading:
            flush(line_start)
            blocks.append(
                Block(
                    block_index=len(blocks),
                    start_char=page_start + line_start,
                    end_char=page_start + line_end,
                    text=stripped,
                    page_index=page_index,
                )
            )
            offset = line_end
            continue

        # Metadata-ish lines in the early document/header area should usually
        # stay isolated, especially before markers/headings.
        if current_is_meta and (next_is_marker or next_is_heading):
            flush(line_start)
            blocks.append(
                Block(
                    block_index=len(blocks),
                    start_char=page_start + line_start,
                    end_char=page_start + line_end,
                    text=stripped,
                    page_index=page_index,
                )
            )
            offset = line_end
            continue

        # List items also stand alone.
        if current_is_list:
            flush(line_start)
            blocks.append(
                Block(
                    block_index=len(blocks),
                    start_char=page_start + line_start,
                    end_char=page_start + line_end,
                    text=stripped,
                    page_index=page_index,
                )
            )
            offset = line_end
            continue

        if current_start is None:
            current_start = line_start

        current_lines.append(raw_line)
        offset = line_end

    flush(len(text))
    return merge_adjacent_heading_blocks(blocks)


def segment_blocks_on_pages(pages: list[tuple[int, int, int, str]]) -> list[Block]:
    all_blocks: list[Block] = []

    for page_index, page_start, _page_end, page_text in pages:
        page_blocks = _segment_single_page(page_index, page_start, page_text)
        for block in page_blocks:
            all_blocks.append(
                Block(
                    block_index=len(all_blocks),
                    start_char=block.start_char,
                    end_char=block.end_char,
                    text=block.text,
                    page_index=block.page_index,
                )
            )

    return all_blocks


def segment_blocks(text: str) -> list[Block]:
    pages = [(0, 0, len(text or ""), text or "")]
    return segment_blocks_on_pages(pages)
