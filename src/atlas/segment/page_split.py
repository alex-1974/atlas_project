from __future__ import annotations


def split_pages(text: str) -> list[tuple[int, int, int, str]]:
    """
    Split text into pages using form-feed characters.

    Returns tuples:
        (page_index, start_char, end_char, page_text)

    If no form-feed exists, the whole text becomes one page.
    """
    if text is None:
        return []

    parts = text.split("\f")
    pages: list[tuple[int, int, int, str]] = []

    start = 0
    for page_index, part in enumerate(parts):
        end = start + len(part)
        pages.append((page_index, start, end, part))
        start = end + 1  # account for removed \f

    return pages
