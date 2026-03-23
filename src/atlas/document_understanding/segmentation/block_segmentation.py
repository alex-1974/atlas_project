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

from dataclasses import dataclass
from statistics import median


@dataclass(slots=True, frozen=True)
class LayoutLine:
    page_index: int
    reading_order: int
    text: str
    x0: float | None
    y0: float | None
    x1: float | None
    y1: float | None
    page_width: float | None
    page_height: float | None
    font_name: str | None = None
    font_size: float | None = None
    font_flags: int | None = None
    is_bold: bool = False
    is_italic: bool = False


@dataclass(slots=True, frozen=True)
class InducedBlock:
    page_index: int
    text: str
    x0: float | None
    y0: float | None
    x1: float | None
    y1: float | None
    page_width: float | None
    page_height: float | None
    line_count: int


LINE_GAP_FACTOR = 1.75
FONT_DELTA_BREAK = 1.5
X_ALIGN_TOLERANCE = 24.0
COLUMN_SHIFT_TOLERANCE = 60.0
WIDE_WIDTH_RATIO = 0.72
SHORT_LINE_WORDS = 4
TITLE_CASE_WORDS_MAX = 14


def _normalize_line_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _word_count(text: str) -> int:
    return len(_normalize_line_text(text).split())


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _line_height(line: LayoutLine) -> float | None:
    if line.y0 is None or line.y1 is None:
        return None
    return float(line.y1) - float(line.y0)


def _line_gap(prev: LayoutLine, cur: LayoutLine) -> float | None:
    if prev.y1 is None or cur.y0 is None:
        return None
    return float(cur.y0) - float(prev.y1)


def _width(line: LayoutLine) -> float | None:
    if line.x0 is None or line.x1 is None:
        return None
    return float(line.x1) - float(line.x0)


def _width_ratio(line: LayoutLine) -> float | None:
    width = _width(line)
    if width is None or line.page_width in (None, 0):
        return None
    return float(width) / float(line.page_width)


def _same_columnish(prev: LayoutLine, cur: LayoutLine) -> bool:
    if prev.x0 is None or cur.x0 is None:
        return True
    return abs(float(prev.x0) - float(cur.x0)) <= COLUMN_SHIFT_TOLERANCE


def _font_continuity(prev: LayoutLine, cur: LayoutLine) -> bool:
    if prev.font_size is not None and cur.font_size is not None:
        if abs(float(prev.font_size) - float(cur.font_size)) > FONT_DELTA_BREAK:
            return False

    if prev.font_name and cur.font_name and prev.font_name != cur.font_name:
        # font family change can still be okay if very similar in size and line shape,
        # so do not hard-break solely on name.
        pass

    return True


def _looks_caption_line(text: str) -> bool:
    low = _normalize_line_text(text).lower()
    return low.startswith(("figure ", "fig.", "table ", "plate "))


def _looks_meta_line(text: str) -> bool:
    low = _normalize_line_text(text).lower()
    return any(
        token in low
        for token in (
            "doi:",
            "doi ",
            "copyright",
            "©",
            "vol.",
            "volume",
            "issue",
            "vernacular architecture",
        )
    )


def _looks_running_header_like(text: str) -> bool:
    value = _normalize_line_text(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc > 16:
        return False

    if value[:1].isdigit():
        return True

    if _caps_ratio(value) >= 0.65:
        return True

    return False


def _looks_short_headingish_line(text: str) -> bool:
    value = _normalize_line_text(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc == 0 or wc > TITLE_CASE_WORDS_MAX:
        return False

    if value.endswith(":"):
        return True

    if wc <= 3 and _caps_ratio(value) >= 0.45:
        return True

    if value.istitle() and wc <= 8:
        return True

    return False


def _looks_body_continuation(text: str) -> bool:
    value = _normalize_line_text(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc >= 8:
        return True
    if wc >= 5 and ("," in value or value.endswith(".")):
        return True
    return False


def _median_positive_gap(lines: list[LayoutLine]) -> float:
    gaps = []
    for i in range(1, len(lines)):
        gap = _line_gap(lines[i - 1], lines[i])
        if gap is not None and gap >= 0:
            gaps.append(gap)
    if not gaps:
        return 12.0
    return float(median(gaps))


def _should_start_new_block(
    current_lines: list[LayoutLine],
    cur: LayoutLine,
    page_gap_baseline: float,
) -> bool:
    prev = current_lines[-1]
    prev_text = _normalize_line_text(prev.text)
    cur_text = _normalize_line_text(cur.text)

    # hard separators
    if _looks_caption_line(cur_text) or _looks_caption_line(prev_text):
        return True

    if _looks_meta_line(cur_text) or _looks_meta_line(prev_text):
        return True

    # running furniture should not fuse with normal body
    if _looks_running_header_like(prev_text) and _looks_body_continuation(cur_text):
        return True

    # wide -> narrow or narrow -> wide often means region break
    prev_width_ratio = _width_ratio(prev)
    cur_width_ratio = _width_ratio(cur)
    if prev_width_ratio is not None and cur_width_ratio is not None:
        if (prev_width_ratio >= WIDE_WIDTH_RATIO) != (cur_width_ratio >= WIDE_WIDTH_RATIO):
            return True

    # strong x shift suggests column or region change
    if not _same_columnish(prev, cur):
        return True

    # font shift
    if not _font_continuity(prev, cur):
        return True

    # large vertical break
    gap = _line_gap(prev, cur)
    if gap is not None and gap > max(8.0, page_gap_baseline * LINE_GAP_FACTOR):
        return True

    # short headingish line should usually stand alone before body
    if len(current_lines) == 1 and _looks_short_headingish_line(prev_text) and _looks_body_continuation(cur_text):
        return True

    # very short line followed by long body line
    if _word_count(prev_text) <= SHORT_LINE_WORDS and _word_count(cur_text) >= 8:
        return True

    return False


def _bbox_union(lines: list[LayoutLine]) -> tuple[float | None, float | None, float | None, float | None]:
    xs0 = [float(l.x0) for l in lines if l.x0 is not None]
    ys0 = [float(l.y0) for l in lines if l.y0 is not None]
    xs1 = [float(l.x1) for l in lines if l.x1 is not None]
    ys1 = [float(l.y1) for l in lines if l.y1 is not None]

    if not xs0:
        return None, None, None, None

    return min(xs0), min(ys0), max(xs1), max(ys1)


def _merge_block_text(lines: list[LayoutLine]) -> str:
    return "\n".join(_normalize_line_text(line.text) for line in lines if _normalize_line_text(line.text))


def induce_blocks_from_lines(page_lines: list[LayoutLine]) -> list[InducedBlock]:
    if not page_lines:
        return []

    page_lines = sorted(page_lines, key=lambda l: l.reading_order)
    page_gap_baseline = _median_positive_gap(page_lines)

    groups: list[list[LayoutLine]] = []
    current: list[LayoutLine] = [page_lines[0]]

    for line in page_lines[1:]:
        if _should_start_new_block(current, line, page_gap_baseline):
            groups.append(current)
            current = [line]
        else:
            current.append(line)

    groups.append(current)

    out: list[InducedBlock] = []
    for group in groups:
        x0, y0, x1, y1 = _bbox_union(group)
        text = _merge_block_text(group)
        if not text:
            continue

        first = group[0]
        out.append(
            InducedBlock(
                page_index=first.page_index,
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                page_width=first.page_width,
                page_height=first.page_height,
                line_count=len(group),
            )
        )

    return out
