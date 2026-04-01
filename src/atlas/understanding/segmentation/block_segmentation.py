# src/atlas/understanding/segmentation/block_segmentation.py
"""Low-level block induction from layout lines.

Pure algorithm — no database access, no Atlas imports.
Takes a list of LayoutLine objects (one page) and returns InducedBlock objects.

The segmentation logic is unchanged from the old system. Only the
dataclass definitions and module location have moved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median


# ── Data types ────────────────────────────────────────────────────────────────

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


# ── Thresholds ────────────────────────────────────────────────────────────────

LINE_GAP_FACTOR       = 1.75   # gap > median * factor → new block
FONT_DELTA_BREAK      = 1.5    # pt difference → font break
COLUMN_SHIFT_TOLERANCE = 60.0  # pt x0 shift → column change
WIDE_WIDTH_RATIO      = 0.72   # fraction of page width
SHORT_LINE_WORDS      = 4      # words ≤ this + long next → break
TITLE_CASE_WORDS_MAX  = 14


# ── Letter-spacing detection ──────────────────────────────────────────────────
#
# PDF extraction sometimes encodes letter-spaced headings as individual
# characters separated by spaces, with double spaces between words:
#     'C A S T L E  H I L L'  (single spaces between chars, double between words)
#     'T H E  P A T T E R N  O F  B U R G A G E'
#
# These double spaces are the only record of word boundaries.  They must
# be preserved through the segmentation pipeline so that Layer 3 can
# recover the readable title ('CASTLE HILL') via normalize_letter_spaced().
#
# Detection uses a pure regex — no Atlas imports, keeping this module
# self-contained.

_LETTER_SPACED_RE = re.compile(
    r'^(?:[A-Za-z\u00C0-\u00FF]{1,3}[ \t]+){3,}[A-Za-z\u00C0-\u00FF]{1,3}\s*$'
)


def _is_letter_spaced_line(text: str) -> bool:
    """True if the line looks like letter-spaced text.

    Matches: 'B U R G A G E  P L O T S', 'T H E  P A T T E R N  O F ...'
    Does not match: normal prose, titles, captions.
    Requires at least 4 space-separated tokens of 1-3 chars each.
    """
    if not text:
        return False
    # Use the normalised form (single spaces) for pattern matching,
    # but only apply if no run of 2+ spaces is present (already collapsed).
    normalised = " ".join(text.split())
    return bool(_LETTER_SPACED_RE.match(normalised))


# ── Text helpers ──────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """Normalise text for segmentation logic.

    For letter-spaced text, preserves double spaces (word boundaries).
    For all other text, collapses runs of whitespace to a single space.
    """
    if not text:
        return ""
    if "  " in text and _is_letter_spaced_line(text):
        # Preserve double spaces — they encode word boundaries
        return text.strip()
    return " ".join(text.split()).strip()


def _word_count(text: str) -> int:
    return len(" ".join(text.split()).split())


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _line_gap(prev: LayoutLine, cur: LayoutLine) -> float | None:
    if prev.y1 is None or cur.y0 is None:
        return None
    return float(cur.y0) - float(prev.y1)


def _width_ratio(line: LayoutLine) -> float | None:
    if line.x0 is None or line.x1 is None or not line.page_width:
        return None
    return (float(line.x1) - float(line.x0)) / float(line.page_width)


def _same_columnish(prev: LayoutLine, cur: LayoutLine) -> bool:
    if prev.x0 is None or cur.x0 is None:
        return True
    return abs(float(prev.x0) - float(cur.x0)) <= COLUMN_SHIFT_TOLERANCE


def _font_continuity(prev: LayoutLine, cur: LayoutLine) -> bool:
    if prev.font_size is not None and cur.font_size is not None:
        if abs(float(prev.font_size) - float(cur.font_size)) > FONT_DELTA_BREAK:
            return False
    return True


# ── Line-type classifiers ────────────────────────────────────────────────────

def _looks_caption_line(text: str) -> bool:
    low = _norm(text).lower()
    return low.startswith(("figure ", "fig.", "table ", "plate "))


def _looks_meta_line(text: str) -> bool:
    low = _norm(text).lower()
    return any(tok in low for tok in (
        "doi:", "doi ", "copyright", "©", "vol.", "volume", "issue",
    ))


def _looks_running_header_like(text: str) -> bool:
    value = _norm(text)
    if not value or _word_count(value) > 16:
        return False
    return value[:1].isdigit() or _caps_ratio(value) >= 0.65


def _looks_short_headingish_line(text: str) -> bool:
    value = _norm(text)
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
    value = _norm(text)
    if not value:
        return False
    wc = _word_count(value)
    return wc >= 8 or (wc >= 5 and ("," in value or value.endswith(".")))


# ── Block boundary decision ───────────────────────────────────────────────────

def _median_positive_gap(lines: list[LayoutLine]) -> float:
    gaps = [
        g for i in range(1, len(lines))
        if (g := _line_gap(lines[i - 1], lines[i])) is not None and g >= 0
    ]
    return float(median(gaps)) if gaps else 12.0


def _should_start_new_block(
    current_lines: list[LayoutLine],
    cur: LayoutLine,
    page_gap_baseline: float,
) -> bool:
    prev = current_lines[-1]
    prev_text = _norm(prev.text)
    cur_text  = _norm(cur.text)

    # Caption / meta lines always stand alone
    if _looks_caption_line(cur_text) or _looks_caption_line(prev_text):
        return True
    if _looks_meta_line(cur_text) or _looks_meta_line(prev_text):
        return True

    # Running header followed by body → break
    if _looks_running_header_like(prev_text) and _looks_body_continuation(cur_text):
        return True

    # Width-category change (wide ↔ narrow) signals a region boundary
    prev_wr = _width_ratio(prev)
    cur_wr  = _width_ratio(cur)
    if prev_wr is not None and cur_wr is not None:
        if (prev_wr >= WIDE_WIDTH_RATIO) != (cur_wr >= WIDE_WIDTH_RATIO):
            return True

    # Column shift
    if not _same_columnish(prev, cur):
        return True

    # Font size jump
    if not _font_continuity(prev, cur):
        return True

    # Large vertical gap
    gap = _line_gap(prev, cur)
    if gap is not None and gap > max(8.0, page_gap_baseline * LINE_GAP_FACTOR):
        return True

    # Short heading-ish line before body
    if (len(current_lines) == 1
            and _looks_short_headingish_line(prev_text)
            and _looks_body_continuation(cur_text)):
        return True

    # Very short line followed by long body line
    if _word_count(prev_text) <= SHORT_LINE_WORDS and _word_count(cur_text) >= 8:
        return True

    return False


# ── Assembly ──────────────────────────────────────────────────────────────────

def _bbox_union(
    lines: list[LayoutLine],
) -> tuple[float | None, float | None, float | None, float | None]:
    xs0 = [float(l.x0) for l in lines if l.x0 is not None]
    ys0 = [float(l.y0) for l in lines if l.y0 is not None]
    xs1 = [float(l.x1) for l in lines if l.x1 is not None]
    ys1 = [float(l.y1) for l in lines if l.y1 is not None]
    if not xs0:
        return None, None, None, None
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _merge_text(lines: list[LayoutLine]) -> str:
    """Merge line texts into a block text.

    Preserves double spaces in letter-spaced lines (word boundaries).
    Uses newline as separator between lines — the normalisation is
    done per-line via _norm(), not on the joined result.
    """
    parts = [_norm(l.text) for l in lines if _norm(l.text)]
    return "\n".join(parts)


def induce_blocks_from_lines(page_lines: list[LayoutLine]) -> list[InducedBlock]:
    """Group layout lines into blocks using geometric and typographic cues.

    Args:
        page_lines: All LayoutLine objects for a single page, in any order.

    Returns:
        Ordered list of InducedBlock objects for that page.
    """
    if not page_lines:
        return []

    page_lines = sorted(page_lines, key=lambda l: l.reading_order)
    baseline   = _median_positive_gap(page_lines)

    groups: list[list[LayoutLine]] = []
    current: list[LayoutLine] = [page_lines[0]]

    for line in page_lines[1:]:
        if _should_start_new_block(current, line, baseline):
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    groups.append(current)

    out: list[InducedBlock] = []
    for group in groups:
        text = _merge_text(group)
        if not text:
            continue
        x0, y0, x1, y1 = _bbox_union(group)
        first = group[0]
        out.append(InducedBlock(
            page_index=first.page_index,
            text=text,
            x0=x0, y0=y0, x1=x1, y1=y1,
            page_width=first.page_width,
            page_height=first.page_height,
            line_count=len(group),
        ))

    return out
