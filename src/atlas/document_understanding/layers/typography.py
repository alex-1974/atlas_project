# src/atlas/document_understanding/layers/typography.py

from __future__ import annotations

from collections import Counter, defaultdict

from atlas.document_understanding.persistence.repository import Repository
from atlas.document_understanding.core.coordinate_system import DocumentCoordinateSystem


def _normalize_font_name(font_name: str | None) -> str | None:
    if not font_name:
        return None
    name = font_name.strip()
    return name or None


def _font_family_hint(font_name: str | None) -> str | None:
    """
    Coarse normalization only.
    Later this can be replaced by a stronger font taxonomy.
    """
    name = _normalize_font_name(font_name)
    if not name:
        return None

    lower = name.lower()

    if any(token in lower for token in ("times", "garamond", "georgia", "baskerville", "serif")):
        return "serif"
    if any(token in lower for token in ("arial", "helvetica", "calibri", "verdana", "sans", "univers")):
        return "sans"
    if any(token in lower for token in ("courier", "mono", "consolas", "menlo")):
        return "mono"

    return "unknown"


def _is_bold(font_name: str | None, font_weight: float | int | None) -> bool:
    if font_weight is not None:
        try:
            if float(font_weight) >= 600:
                return True
        except (TypeError, ValueError):
            pass

    name = (font_name or "").lower()
    return any(token in name for token in ("bold", "black", "heavy", "demi", "semibold"))


def _is_italic(font_name: str | None) -> bool:
    name = (font_name or "").lower()
    return any(token in name for token in ("italic", "oblique", "kursiv"))


def _caps_stats(text: str) -> tuple[int, int]:
    letters = 0
    upper = 0
    for ch in text:
        if ch.isalpha():
            letters += 1
            if ch.isupper():
                upper += 1
    return letters, upper


def _is_all_caps(text: str) -> bool:
    letters, upper = _caps_stats(text)
    return letters > 0 and upper == letters


def _is_small_caps(
    text: str,
    font_name: str | None,
    all_caps: bool,
) -> bool:
    """
    Conservative heuristic.
    True small caps detection is difficult without glyph-level metrics.
    """
    if all_caps:
        return False

    name = (font_name or "").lower()
    if "smallcaps" in name or "small-caps" in name or "sc" in name:
        letters, upper = _caps_stats(text)
        return letters > 0 and upper > 0

    return False


def _safe_neighbor_change(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    return a != b


def _group_by_page(blocks: list[dict]) -> dict[int, list[dict]]:
    pages: dict[int, list[dict]] = defaultdict(list)
    for block in blocks:
        page_index = block.get("page_index")
        if page_index is not None:
            pages[int(page_index)].append(block)
    return pages


def _page_max_font_sizes(blocks: list[dict]) -> dict[int, float]:
    result: dict[int, float] = {}
    for page_index, page_blocks in _group_by_page(blocks).items():
        values = []
        for block in page_blocks:
            font_size = block.get("font_size")
            if font_size is not None:
                try:
                    values.append(float(font_size))
                except (TypeError, ValueError):
                    pass
        if values:
            result[page_index] = max(values)
    return result


def _document_font_mode(blocks: list[dict]) -> str | None:
    names = [
        _normalize_font_name(block.get("font_name"))
        for block in blocks
        if block.get("font_name")
    ]
    names = [n for n in names if n]
    if not names:
        return None
    return Counter(names).most_common(1)[0][0]


def compute_typography(repository: Repository, doc_id: int) -> None:
    """
    Typography layer.

    Raw font information may come from extraction.
    This layer converts it into normalized and reusable block-level features.
    """
    blocks = repository.fetch_blocks(doc_id)
    if not blocks:
        return

    coord: DocumentCoordinateSystem = repository.fetch_coordinate_system(doc_id)
    page_max_sizes = _page_max_font_sizes(blocks)
    document_font_mode = _document_font_mode(blocks)

    rows: list[dict] = []

    for idx, block in enumerate(blocks):
        text = (block.get("text") or "").strip()

        font_name = _normalize_font_name(block.get("font_name"))
        font_family = _font_family_hint(font_name)

        font_size = block.get("font_size")
        try:
            font_size_value = float(font_size) if font_size is not None else None
        except (TypeError, ValueError):
            font_size_value = None

        font_ratio = coord.font_ratio(font_size_value)

        page_index = block.get("page_index")
        page_max = page_max_sizes.get(int(page_index)) if page_index is not None and int(page_index) in page_max_sizes else None
        largest_on_page = (
            font_size_value is not None
            and page_max is not None
            and abs(font_size_value - page_max) < 1e-9
        )

        bold = _is_bold(block.get("font_name"), block.get("font_weight"))
        italic = _is_italic(block.get("font_name"))

        all_caps = _is_all_caps(text)
        small_caps = _is_small_caps(text=text, font_name=font_name, all_caps=all_caps)

        prev_block = blocks[idx - 1] if idx > 0 else None
        next_block = blocks[idx + 1] if idx + 1 < len(blocks) else None

        prev_font_name = _normalize_font_name(prev_block.get("font_name")) if prev_block else None
        next_font_name = _normalize_font_name(next_block.get("font_name")) if next_block else None

        prev_font_size = prev_block.get("font_size") if prev_block else None
        next_font_size = next_block.get("font_size") if next_block else None

        try:
            prev_font_size = float(prev_font_size) if prev_font_size is not None else None
        except (TypeError, ValueError):
            prev_font_size = None
        try:
            next_font_size = float(next_font_size) if next_font_size is not None else None
        except (TypeError, ValueError):
            next_font_size = None

        font_name_change_prev = _safe_neighbor_change(font_name, prev_font_name)
        font_name_change_next = _safe_neighbor_change(font_name, next_font_name)
        font_size_change_prev = _safe_neighbor_change(font_size_value, prev_font_size)
        font_size_change_next = _safe_neighbor_change(font_size_value, next_font_size)

        larger_than_prev = (
            font_size_value is not None and prev_font_size is not None and font_size_value > prev_font_size
        )
        larger_than_next = (
            font_size_value is not None and next_font_size is not None and font_size_value > next_font_size
        )

        rows.append(
            {
                "block_id": block["block_id"],
                "font_name": font_name,
                "font_family": font_family,
                "font_size": font_size_value,
                "font_ratio": font_ratio,
                "bold": bold,
                "italic": italic,
                "small_caps": small_caps,
                "all_caps": all_caps,
                "largest_on_page": largest_on_page,
                "larger_than_prev": larger_than_prev,
                "larger_than_next": larger_than_next,
                "font_name_change_prev": font_name_change_prev,
                "font_name_change_next": font_name_change_next,
                "font_size_change_prev": font_size_change_prev,
                "font_size_change_next": font_size_change_next,
                "is_document_font_mode": (font_name == document_font_mode) if font_name else None,
            }
        )

    repository.store_typography_features(doc_id, rows)
