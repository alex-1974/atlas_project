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


def _is_sentence_end(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?"))


def _is_lower_start(text: str) -> bool:
    t = text.lstrip()
    return t[:1].islower() if t else False


def _is_upper_start(text: str) -> bool:
    t = text.lstrip()
    return t[:1].isupper() if t else False


def _is_hyphenated_join(left: str, right: str) -> bool:
    _ = right
    return left.rstrip().endswith("-")


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _looks_sentence_like(text: str) -> bool:
    t = " ".join(text.split())
    if not t:
        return False

    wc = len(t.split())
    if wc >= 12:
        return True
    if t.endswith(".") and wc >= 6:
        return True
    return False


def _is_caption_block(text: str) -> bool:
    low = text.lower().strip()
    return low.startswith("figure ") or low.startswith("fig. ") or low.startswith("table ")


def _is_reference_like_block(text: str) -> bool:
    low = text.lower()

    if "doi" in low:
        return True

    if "journal" in low or "press" in low or "university press" in low:
        return True

    if "(" in low and ")" in low and any(c.isdigit() for c in low):
        return True

    return False


def _looks_author_like_block(text: str) -> bool:
    t = " ".join(text.split())
    if not t:
        return False

    low = t.lower()
    if any(
        marker in low
        for marker in (
            "doi:",
            "doi.org",
            "journal",
            "vol.",
            "volume",
            "issue",
            "figure ",
            "table ",
            "copyright",
            "©",
            "abstract",
            "keywords",
            "references",
            "bibliography",
        )
    ):
        return False

    words = [w.strip(",;:.()[]") for w in t.replace("&", " ").replace(" and ", " ").split()]
    words = [w for w in words if w]
    if not (2 <= len(words) <= 8):
        return False

    alpha_words = [w for w in words if any(ch.isalpha() for ch in w)]
    if len(alpha_words) < 2:
        return False

    titlecase_like = 0
    for word in alpha_words:
        if len(word) == 1 and word.isupper():
            titlecase_like += 1
            continue
        if word[:1].isupper():
            titlecase_like += 1

    return titlecase_like >= max(2, len(alpha_words) - 1)


def _looks_title_like_block(text: str) -> bool:
    t = " ".join(text.split())
    if not t:
        return False

    wc = len(t.split())
    if wc == 0 or wc > 18:
        return False

    low = t.lower()
    if any(
        marker in low
        for marker in (
            "doi:",
            "doi.org",
            "journal",
            "vol.",
            "volume",
            "issue",
            "issn",
            "isbn",
            "abstract",
            "keywords",
            "references",
            "bibliography",
            "figure ",
            "table ",
        )
    ):
        return False

    if _looks_sentence_like(t):
        return False

    if t.endswith(":"):
        return False

    if _caps_ratio(t) > 0.65 and wc >= 2:
        return True

    if wc <= 10 and t.istitle():
        return True

    return False


def _looks_heading_prefix(text: str) -> bool:
    t = " ".join(text.split())
    if not t:
        return False

    if len(t) > 140:
        return False

    wc = len(t.split())
    if wc < 3:
        return False

    if t.endswith(":") and wc <= 12:
        return True

    prefix = t[: min(len(t), 60)]
    if _caps_ratio(prefix) > 0.65 and wc >= 4:
        return True

    if re.match(r"^\d+(?:\.\d+)*[.)]?\s+[A-Z]", t):
        return True

    return False


def _split_heading_body_block(text: str) -> list[str]:
    """
    Split patterns like:
    'INTRODUCTION AND METHODS Around 3600 buildings ...'
    into:
    ['INTRODUCTION AND METHODS', 'Around 3600 buildings ...']

    Conservative on purpose.
    """
    t = " ".join(text.split())
    if not t:
        return []

    if not _looks_heading_prefix(t):
        return [t]

    max_scan = min(len(t), 140)
    for i in range(8, max_scan):
        left = t[:i].rstrip()
        right = t[i:].lstrip()

        if not left or not right:
            continue

        left_wc = len(left.split())
        right_wc = len(right.split())

        if left_wc < 2 or left_wc > 12:
            continue
        if right_wc < 4:
            continue

        left_caps = _caps_ratio(left)
        right_starts_sentence = _is_upper_start(right) and " " in right
        right_looks_running = right_wc >= 6 or _is_sentence_end(right)

        if left_caps > 0.70 and right_starts_sentence and right_looks_running:
            return [left, right]

    return [t]


def _merge_blocks(blocks: list[str]) -> list[str]:
    """
    Merge artificially fragmented blocks after the initial split pass.

    v2: more defensive than v1.
    Especially avoids merging early title/author material with first body text.
    """
    if not blocks:
        return []

    merged: list[str] = []
    current = blocks[0]

    for idx, nxt in enumerate(blocks[1:], start=1):
        current_norm = " ".join(current.split())
        nxt_norm = " ".join(nxt.split())

        merge = False

        current_heading = is_heading_like_line(current_norm)
        nxt_heading = is_heading_like_line(nxt_norm)
        current_toc = is_toc_like_line(current_norm)
        nxt_toc = is_toc_like_line(nxt_norm)
        current_list = is_list_like_line(current_norm)
        nxt_list = is_list_like_line(nxt_norm)
        current_meta = is_metadata_like_line(current_norm)
        nxt_meta = is_metadata_like_line(nxt_norm)

        current_caption = _is_caption_block(current_norm)
        nxt_caption = _is_caption_block(nxt_norm)
        current_ref = _is_reference_like_block(current_norm)
        nxt_ref = _is_reference_like_block(nxt_norm)

        current_title_like = _looks_title_like_block(current_norm)
        nxt_title_like = _looks_title_like_block(nxt_norm)
        current_author_like = _looks_author_like_block(current_norm)
        nxt_author_like = _looks_author_like_block(nxt_norm)

        early_window = idx <= 8

        protected = (
            current_heading
            or nxt_heading
            or current_toc
            or nxt_toc
            or current_list
            or nxt_list
            or current_caption
            or nxt_caption
        )

        # Hard stop: don't merge title/author-ish front matter with body.
        if early_window:
            if current_title_like or current_author_like or nxt_title_like or nxt_author_like:
                merged.append(current_norm.strip())
                current = nxt_norm
                continue

        if _is_hyphenated_join(current_norm, nxt_norm):
            current = current_norm.rstrip("-") + nxt_norm
            continue

        if not protected:
            # safest merge: sentence continuation with lowercase start
            if not _is_sentence_end(current_norm) and _is_lower_start(nxt_norm):
                merge = True

            # short fragment may merge, but not in front matter and not with title/author/reference/meta
            elif (
                len(current_norm.split()) < 6
                and not nxt_meta
                and not nxt_ref
                and not early_window
                and not current_title_like
                and not current_author_like
            ):
                merge = True

            # punctuation continuation, but avoid front matter
            elif (
                current_norm.rstrip().endswith((",", ";"))
                and not nxt_heading
                and not early_window
            ):
                merge = True

            # explicit metadata line may merge with long running line,
            # but not in early front matter and not if title/author-like
            elif (
                current_meta
                and len(nxt_norm.split()) >= 12
                and not nxt_heading
                and not nxt_toc
                and not early_window
                and not current_title_like
                and not current_author_like
            ):
                merge = True

            # contiguous references may merge, but only outside early front matter
            elif current_ref and nxt_ref and not early_window:
                merge = True

        if merge:
            current = current_norm + " " + nxt_norm
        else:
            merged.append(current_norm.strip())
            current = nxt_norm

    merged.append(" ".join(current.split()).strip())
    return merged


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

    # merge pass for artificially fragmented blocks
    result = _merge_blocks(result)

    # post-pass: split heading+body combinations
    final: list[str] = []
    for block in result:
        parts = _split_heading_body_block(block)
        for part in parts:
            part = part.strip()
            if len(part) >= 3:
                final.append(part)

    return final
