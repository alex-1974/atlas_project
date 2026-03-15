"""
Header reconstruction for section parsing.

PDF layout often splits numbered headers into multiple blocks:

    4.4.2.
    Holzverbindungen im Fachwerkbau

This module merges such blocks before section tree construction.
"""

import re


HEADER_NUMBER_RE = re.compile(r"^\d+(\.\d+)*\.?$")
PAGE_NUMBER_RE = re.compile(r"^-?\s*\d+\s*$")


def is_header_number(text: str) -> bool:
    text = text.strip()
    return bool(HEADER_NUMBER_RE.match(text))


def is_page_number(text: str) -> bool:
    text = text.strip()
    return bool(PAGE_NUMBER_RE.match(text))


def vertical_distance(a, b):
    """
    Estimate vertical distance between two blocks.

    Expects bbox format:
    (x0, y0, x1, y1)
    """
    return abs(a["bbox"][1] - b["bbox"][1])


def merge_split_headers(blocks, max_vertical_gap=25):
    """
    Merge header-number blocks with their title blocks.

    Parameters
    ----------
    blocks : list[dict]
        Layout blocks with fields:
        - text
        - bbox
        - page

    Returns
    -------
    list[dict]
        New block list with reconstructed headers.
    """

    merged = []
    i = 0
    n = len(blocks)

    while i < n:

        block = blocks[i]
        text = block["text"].strip()

        # skip pure page numbers
        if is_page_number(text):
            i += 1
            continue

        if is_header_number(text) and i + 1 < n:

            next_block = blocks[i + 1]

            # same page
            if block["page"] == next_block["page"]:

                gap = vertical_distance(block, next_block)

                if gap <= max_vertical_gap:

                    title = next_block["text"].strip()

                    if not is_header_number(title):

                        merged_block = block.copy()
                        merged_block["text"] = f"{text} {title}"

                        merged.append(merged_block)

                        i += 2
                        continue

        merged.append(block)
        i += 1

    return merged
