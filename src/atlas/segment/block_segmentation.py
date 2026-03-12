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

LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.\)])\s+")

SENTENCE_HINT_WORDS = {
    "the", "and", "with", "from", "that", "this", "are", "is", "was", "were",
    "der", "die", "das", "und", "mit", "von", "ein", "eine", "einer",
}


def is_blank_line(line: str) -> bool:
    return not line.strip()


def is_region_marker(line: str) -> bool:
    return bool(REGION_MARKER_RE.match((line or "").strip()))


def _normalize_inline_whitespace(text: str) -> str:
    return " ".join((text or "").strip().split())


def is_heading_like(line: str) -> bool:
    value = _normalize_inline_whitespace(line)
    if not value:
        return False

    if REGION_MARKER_RE.match(value):
        return True

    if len(value) > 100:
        return False

    if LIST_MARKER_RE.match(value):
        return False

    # headings rarely end with full stop
    if value.endswith("."):
        return False

    if "," in value or ";" in value:
        return False

    words = value.split()
    if len(words) > 8:
        return False

    lower_words = {w.lower() for w in words}
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
    if ratio < 0.25:
        return False

    return True


def _normalize_block_text(lines: list[str]) -> str:
    # Join once, avoid per-line rstrip copies.
    text = "".join(lines).replace("\x00", "")
    # Normalize horizontal whitespace line-wise but keep paragraph structure.
    norm_lines = [" ".join(line.rstrip("\n").split()) for line in text.splitlines()]
    text = "\n".join(norm_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def merge_adjacent_heading_blocks(blocks: list[Block]) -> list[Block]:
    if not blocks:
        return []

    merged: list[Block] = []
    append_merged = merged.append
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
                and is_heading_like(current.text)
                and is_heading_like(nxt.text)
            ):
                append_merged(
                    Block(
                        block_index=0,  # fixed during final reindex
                        start_char=current.start_char,
                        end_char=nxt.end_char,
                        text=f"{current.text} {nxt.text}".strip(),
                        page_index=current.page_index,
                    )
                )
                i += 2
                continue

        append_merged(current)
        i += 1

    # Single final reindex pass.
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
    append_block = blocks.append

    current_lines: list[str] = []
    append_current = current_lines.append
    current_start: int | None = None
    offset = 0

    def flush(end_offset: int) -> None:
        nonlocal current_lines, append_current, current_start

        if current_start is None:
            current_lines = []
            append_current = current_lines.append
            return

        block_text = _normalize_block_text(current_lines)
        if block_text:
            append_block(
                Block(
                    block_index=len(blocks),
                    start_char=page_start + current_start,
                    end_char=page_start + end_offset,
                    text=block_text,
                    page_index=page_index,
                )
            )

        current_lines = []
        append_current = current_lines.append
        current_start = None

    for raw_line in lines:
        line_start = offset
        line_end = offset + len(raw_line)
        stripped = raw_line.strip()

        if not stripped:
            flush(line_start)
            offset = line_end
            continue

        if REGION_MARKER_RE.match(stripped):
            flush(line_start)
            append_block(
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

        if is_heading_like(stripped):
            flush(line_start)
            append_block(
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

        append_current(raw_line)
        offset = line_end

    flush(len(text))
    return merge_adjacent_heading_blocks(blocks)


def segment_blocks_on_pages(pages: list[tuple[int, int, int, str]]) -> list[Block]:
    all_blocks: list[Block] = []
    append_all = all_blocks.append

    for page_index, page_start, _page_end, page_text in pages:
        page_blocks = _segment_single_page(page_index, page_start, page_text)
        for block in page_blocks:
            append_all(
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
