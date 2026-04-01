# src/atlas/pipeline/extract/layout.py
"""Extract fine-grained layout data from a PDF for the DU pipeline.

Populates three tables that the DU pipeline reads:

  du_layout_lines   — one row per text line (for segmentation/blocks.py)
  du_layout_spans   — one row per text span (for measure/typography.py)
  du_layout_images  — one row per image block (for geometry.py near_image_score)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import fitz  # PyMuPDF


# ── Schema helpers ────────────────────────────────────────────────────────────

_CREATE_LAYOUT_LINES = """
CREATE TABLE IF NOT EXISTS du_layout_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT    NOT NULL REFERENCES documents(document_id),
    page_index      INTEGER NOT NULL,
    reading_order   INTEGER NOT NULL,
    text            TEXT,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    page_width      REAL,
    page_height     REAL,
    font_name       TEXT,
    font_size       REAL,
    font_flags      INTEGER,
    is_bold         INTEGER,
    is_italic       INTEGER,
    color           INTEGER DEFAULT 0,
    UNIQUE(document_id, page_index, reading_order)
)
"""

_CREATE_LAYOUT_IMAGES = """
CREATE TABLE IF NOT EXISTS du_layout_images (
    image_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT    NOT NULL REFERENCES documents(document_id),
    page_index  INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL
)
"""

_CREATE_LAYOUT_DRAWINGS = """
CREATE TABLE IF NOT EXISTS du_layout_drawings (
    drawing_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT    NOT NULL REFERENCES documents(document_id),
    page_index  INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    fill_r REAL, fill_g REAL, fill_b REAL
)
"""

_CREATE_LAYOUT_SPANS = """
CREATE TABLE IF NOT EXISTS du_layout_spans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT    NOT NULL REFERENCES documents(document_id),
    page_index      INTEGER NOT NULL,
    reading_order   INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    text            TEXT,
    font_name       TEXT,
    font_size       REAL,
    font_flags      INTEGER,
    is_bold         INTEGER,
    is_italic       INTEGER,
    color           INTEGER DEFAULT 0,
    char_spacing    REAL    DEFAULT 0.0,
    UNIQUE(document_id, page_index, reading_order)
)
"""


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_LAYOUT_LINES)
    conn.execute(_CREATE_LAYOUT_SPANS)
    conn.execute(_CREATE_LAYOUT_IMAGES)
    conn.execute(_CREATE_LAYOUT_DRAWINGS)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_du_layout_images_doc "
        "ON du_layout_images(document_id, page_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_du_layout_drawings_doc "
        "ON du_layout_drawings(document_id, page_index)"
    )
    conn.commit()


# ── Font flag helpers ─────────────────────────────────────────────────────────

# PyMuPDF font flags (fitz.TEXT_FONT_*)
_FLAG_BOLD   = 1 << 4   # 16
_FLAG_ITALIC = 1 << 1   # 2


def _is_bold(flags: int) -> bool:
    return bool(flags & _FLAG_BOLD)


def _is_italic(flags: int) -> bool:
    return bool(flags & _FLAG_ITALIC)


_FLAG_SERIF = 1 << 2   # 4 — serifed font


def _is_serif(flags: int) -> bool:
    return bool(flags & _FLAG_SERIF)


def _span_text(span: dict) -> str:
    """Extract text from a span — works with both old and new PyMuPDF API.

    PyMuPDF < 1.24: text is in span['text']
    PyMuPDF >= 1.24: text is assembled from span['chars'][n]['c']
    """
    text = span.get("text", "")
    if text:
        return text
    return "".join(ch.get("c", "") for ch in span.get("chars", []))


def _compute_char_spacing(span: dict) -> float:
    """Compute mean character gap relative to font size.

    Returns a ratio: mean_gap / font_size.
      ~0.3–0.6  normal proportional text
      ~0.85+    letter-spaced text
    Returns 0.0 if fewer than 3 characters or font_size is zero.
    """
    chars = span.get("chars", [])
    fs = float(span.get("size", 0.0))
    if len(chars) < 3 or fs <= 0:
        return 0.0
    gaps = []
    for i in range(1, len(chars)):
        dx = float(chars[i]["origin"][0]) - float(chars[i - 1]["origin"][0])
        if dx > 0:
            gaps.append(dx)
    if not gaps:
        return 0.0
    return sum(gaps) / len(gaps) / fs


def _reconstruct_letter_spaced_text(span: dict) -> str:
    """Reconstruct readable text from a letter-spaced span.

    For spans where char_spacing > 0.85, inserts double spaces at word
    boundaries detected from gaps between char origins.  A gap is a word
    boundary when it is ≥ 1.8× the mean inter-character gap.

    Double spaces are the convention used by normalize_letter_spaced() in
    text_patterns.py to detect word boundaries during collapsing:
        'C A S T L E  H I L L'  →  'CASTLE HILL'

    Falls back to raw span text if chars data is unavailable.
    """
    chars = span.get("chars", [])
    if len(chars) < 3:
        return _span_text(span)
    fs = float(span.get("size", 0.0))
    if fs <= 0:
        return _span_text(span)

    # Collect positive inter-character gaps with their positions
    gap_pairs: list[tuple[int, float]] = []
    for i in range(1, len(chars)):
        dx = float(chars[i]["origin"][0]) - float(chars[i - 1]["origin"][0])
        if dx > 0:
            gap_pairs.append((i, dx))

    if not gap_pairs:
        return _span_text(span)

    mean_gap = sum(g for _, g in gap_pairs) / len(gap_pairs)
    threshold = mean_gap * 1.8  # 1.8× mean = word boundary

    # Build text with double spaces at word boundaries
    result = chars[0].get("c", "")
    for i, dx in gap_pairs:
        result += "  " if dx > threshold else ""
        result += chars[i].get("c", "")
    return result


# ── Extraction ────────────────────────────────────────────────────────────────

def run_extract_layout(conn: sqlite3.Connection,
                       document_id: str,
                       pdf_path: str) -> None:
    """Extract layout lines and spans from every page and persist them.

    Idempotent — DELETE existing rows for this document before inserting.
    """
    _ensure_tables(conn)

    path = Path(pdf_path)
    doc  = fitz.open(path)

    conn.execute(
        "DELETE FROM du_layout_lines WHERE document_id = ?", (document_id,)
    )
    conn.execute(
        "DELETE FROM du_layout_spans WHERE document_id = ?", (document_id,)
    )
    conn.execute(
        "DELETE FROM du_layout_images WHERE document_id = ?", (document_id,)
    )
    conn.execute(
        "DELETE FROM du_layout_drawings WHERE document_id = ?", (document_id,)
    )

    line_rows:     list[tuple] = []
    span_rows:     list[tuple] = []
    image_rows:    list[tuple] = []
    drawing_rows:  list[tuple] = []

    for page_index, page in enumerate(doc):
        width  = float(page.rect.width)
        height = float(page.rect.height)

        # Colored fill drawings → background boxes (sidebars, callouts, etc.)
        # White (1,1,1) and near-white fills are ignored (decorative hairlines).
        for d in page.get_drawings():
            fill = d.get("fill")
            rect = d.get("rect")
            if fill is None or rect is None:
                continue
            r, g, b = (float(fill[0]), float(fill[1]), float(fill[2]))
            # Skip white/near-white and fully transparent
            if r > 0.97 and g > 0.97 and b > 0.97:
                continue
            bw = float(rect[2]) - float(rect[0])
            bh = float(rect[3]) - float(rect[1])
            if bw < 20.0 or bh < 10.0:
                continue  # tiny decorative lines / checkboxes
            drawing_rows.append((
                document_id, page_index,
                float(rect[0]), float(rect[1]),
                float(rect[2]), float(rect[3]),
                r, g, b,
            ))

    for page_index, page in enumerate(doc):
        width  = float(page.rect.width)
        height = float(page.rect.height)

        # rawdict gives blocks → lines → spans with full font info.
        # type=0: text block  |  type=1: image block
        raw = page.get_text("rawdict")
        line_order = 0
        span_order = 0

        for block in raw.get("blocks", []):
            btype = block.get("type", 0)

            # ── Image blocks ──────────────────────────────────────────────
            if btype == 1:
                bb = block.get("bbox", (0, 0, 0, 0))
                bw = float(bb[2]) - float(bb[0])
                bh = float(bb[3]) - float(bb[1])
                # Ignore tiny artefacts (< 20×20 pt) — decorative rules, etc.
                if bw >= 20.0 and bh >= 20.0:
                    image_rows.append((
                        document_id, page_index,
                        float(bb[0]), float(bb[1]),
                        float(bb[2]), float(bb[3]),
                    ))
                continue  # no text in image blocks

            if btype != 0:
                continue  # skip other non-text blocks

            for line in block.get("lines", []):
                bbox = line.get("bbox", (0, 0, 0, 0))
                x0, y0, x1, y1 = (float(v) for v in bbox)

                # Collect all spans to pick dominant font for the line
                spans = line.get("spans", [])
                if not spans:
                    continue

                # Build line text — use reconstructed text for letter-spaced
                # spans so that word boundaries (double spaces) are preserved
                # in du_layout_lines.text and subsequently in du_blocks.text.
                line_parts = []
                for s in spans:
                    cs = _compute_char_spacing(s)
                    if cs > 0.85:
                        line_parts.append(_reconstruct_letter_spaced_text(s))
                    else:
                        line_parts.append(_span_text(s))
                line_text = "".join(line_parts)
                if not line_text.strip():
                    continue

                # Dominant span = longest text
                dominant = max(spans, key=lambda s: len(_span_text(s)))
                font_name  = dominant.get("font", "")
                font_size  = float(dominant.get("size", 0.0))
                font_flags = int(dominant.get("flags", 0))
                bold       = int(_is_bold(font_flags))
                italic     = int(_is_italic(font_flags))
                color      = int(dominant.get("color", 0))

                line_rows.append((
                    document_id, page_index, line_order,
                    line_text, x0, y0, x1, y1,
                    width, height,
                    font_name, font_size, font_flags,
                    bold, italic, color,
                ))
                line_order += 1

                # Individual spans
                for span in spans:
                    cs = _compute_char_spacing(span)
                    # For letter-spaced spans, reconstruct text with double
                    # spaces at word boundaries so normalize_letter_spaced()
                    # can recover 'CASTLE HILL' from 'C A S T L E  H I L L'.
                    if cs > 0.85:
                        stext = _reconstruct_letter_spaced_text(span)
                    else:
                        stext = _span_text(span)
                    if not stext.strip():
                        continue
                    sb = span.get("bbox", (0, 0, 0, 0))
                    sf = int(span.get("flags", 0))
                    sc = int(span.get("color", 0))
                    span_rows.append((
                        document_id, page_index, span_order,
                        float(sb[0]), float(sb[1]), float(sb[2]), float(sb[3]),
                        stext,
                        span.get("font", ""),
                        float(span.get("size", 0.0)),
                        sf,
                        int(_is_bold(sf)),
                        int(_is_italic(sf)),
                        sc,
                        cs,
                    ))
                    span_order += 1

    doc.close()

    conn.executemany(
        """
        INSERT INTO du_layout_drawings
            (document_id, page_index, x0, y0, x1, y1, fill_r, fill_g, fill_b)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        drawing_rows,
    )
    conn.executemany(
        """
        INSERT INTO du_layout_images
            (document_id, page_index, x0, y0, x1, y1)
        VALUES (?,?,?,?,?,?)
        """,
        image_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO du_layout_lines
            (document_id, page_index, reading_order,
             text, x0, y0, x1, y1, page_width, page_height,
             font_name, font_size, font_flags, is_bold, is_italic, color)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        line_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO du_layout_spans
            (document_id, page_index, reading_order,
             x0, y0, x1, y1, text,
             font_name, font_size, font_flags, is_bold, is_italic, color,
             char_spacing)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        span_rows,
    )
    conn.commit()
