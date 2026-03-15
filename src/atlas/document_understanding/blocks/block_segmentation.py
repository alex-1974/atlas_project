from __future__ import annotations

import re


LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
TOC_LINE_RE = re.compile(r"\.{2,}|\s\d{1,3}\s*$")


_METADATA_KEYWORDS = (
    "abstract",
    "summary",
    "keywords",
    "author",
    "gutachter",
    "dissertation",
    "faculty",
    "universität",
    "university",
    "institute",
    "department",
    "issn",
    "isbn",
    "doi",
    "vol.",
    "volume",
    "issue",
)


def normalize_line(line: str) -> str:
    if "\x00" in line:
        line = line.replace("\x00", "")
    if "  " in line or "\t" in line:
        line = re.sub(r"[ \t]+", " ", line)
    return line.rstrip()


def line_word_count(line: str) -> int:
    return len(line.split())


def is_heading_like_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False

    wc = len(text.split())
    if wc > 12 or len(text) > 120:
        return False

    if text.endswith(":"):
        return True
    if wc >= 2 and text.isupper():
        return True
    if wc <= 10 and text.istitle():
        return True

    return False


def is_toc_like_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    return bool(TOC_LINE_RE.search(text))


def is_list_like_line(line: str) -> bool:
    return bool(LIST_MARKER_RE.match(line))


def is_metadata_like_line(line: str) -> bool:
    text = line.strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _METADATA_KEYWORDS)


def _line_features(line: str) -> tuple[str, int, int, bool, bool, bool, bool]:
    text = line.strip()
    wc = len(text.split()) if text else 0
    ln = len(text)
    heading = False
    toc = False
    list_like = False
    metadata = False

    if text:
        if wc <= 12 and ln <= 120:
            if text.endswith(":"):
                heading = True
            elif wc >= 2 and text.isupper():
                heading = True
            elif wc <= 10 and text.istitle():
                heading = True

        toc = bool(TOC_LINE_RE.search(text))
        list_like = bool(LIST_MARKER_RE.match(line))

        lower = text.lower()
        metadata = any(keyword in lower for keyword in _METADATA_KEYWORDS)

    return text, wc, ln, heading, toc, list_like, metadata


def should_split_features(
    prev_wc: int,
    prev_len: int,
    prev_heading: bool,
    prev_toc: bool,
    prev_list: bool,
    prev_meta: bool,
    curr_wc: int,
    curr_len: int,
    curr_heading: bool,
    curr_toc: bool,
    curr_list: bool,
    curr_meta: bool,
) -> bool:
    if prev_heading or prev_toc or prev_list:
        return True

    if curr_heading or curr_toc or curr_list:
        return True

    if curr_meta and prev_wc > 18:
        return True

    if prev_meta and curr_wc > 18:
        return True

    if prev_wc <= 10 and curr_wc >= 18:
        return True

    if prev_wc >= 18 and curr_wc <= 10:
        return True

    if prev_len >= 100 and curr_len <= 55:
        return True

    if prev_len <= 55 and curr_len >= 100:
        return True

    return False


def split_block_by_lines(block_text: str) -> list[str]:
    raw_lines = block_text.splitlines()

    lines: list[str] = []
    for raw in raw_lines:
        line = normalize_line(raw)
        if line.strip():
            lines.append(line)

    if not lines:
        return []

    result: list[str] = []

    first = lines[0]
    (
        _prev_text,
        prev_wc,
        prev_len,
        prev_heading,
        prev_toc,
        prev_list,
        prev_meta,
    ) = _line_features(first)

    current: list[str] = [first]

    for line in lines[1:]:
        (
            _curr_text,
            curr_wc,
            curr_len,
            curr_heading,
            curr_toc,
            curr_list,
            curr_meta,
        ) = _line_features(line)

        if should_split_features(
            prev_wc,
            prev_len,
            prev_heading,
            prev_toc,
            prev_list,
            prev_meta,
            curr_wc,
            curr_len,
            curr_heading,
            curr_toc,
            curr_list,
            curr_meta,
        ):
            text = "\n".join(current).strip()
            if text:
                result.append(text)
            current = [line]
        else:
            current.append(line)

        prev_wc = curr_wc
        prev_len = curr_len
        prev_heading = curr_heading
        prev_toc = curr_toc
        prev_list = curr_list
        prev_meta = curr_meta

    text = "\n".join(current).strip()
    if text:
        result.append(text)

    return result


def segment_page_into_blocks(page_text: str) -> list[str]:
    if not page_text:
        return []

    if "\x00" in page_text:
        page_text = page_text.replace("\x00", "")

    raw_blocks = re.split(r"\n\s*\n+", page_text)

    result: list[str] = []

    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue

        split_blocks = split_block_by_lines(raw)
        for block in split_blocks:
            block = block.strip()
            if len(block) >= 3:
                result.append(block)

    return result
