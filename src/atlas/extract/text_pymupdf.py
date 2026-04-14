from __future__ import annotations

import uuid
from pathlib import Path

import pymupdf as fitz

from atlas.db.connection import get_connection


def _sanitize_text(text: str) -> tuple[str, int]:
    if not text:
        return "", 0
    nul_count = text.count("\x00")
    return text.replace("\x00", ""), nul_count


def _union_bbox(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float | None, float | None, float | None, float | None]:
    if not boxes:
        return None, None, None, None

    xs0 = [b[0] for b in boxes]
    ys0 = [b[1] for b in boxes]
    xs1 = [b[2] for b in boxes]
    ys1 = [b[3] for b in boxes]

    return min(xs0), min(ys0), max(xs1), max(ys1)


def _font_flags_to_style(flags: int | None) -> tuple[bool, bool]:
    if flags is None:
        return False, False
    is_italic = bool(flags & 2)
    is_bold = bool(flags & 16)
    return is_bold, is_italic


def already_extracted(document_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM extracted_texts WHERE document_id = ? LIMIT 1",
            (document_id,),
        )
        return cur.fetchone() is not None


def store_extraction(
    document_id: str,
    extractor: str,
    text_full: str | None,
    text_length: int | None,
    nul_bytes_removed: int,
    extract_status: str,
    extract_error: str | None,
) -> None:
    # Schema (migration 0002): document_id, text, text_length, method
    # Fehler werden in documents.pipeline_error gespeichert, nicht hier.
    if extract_status != "ok" or text_full is None:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO extracted_texts (document_id, text, text_length, method)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, text_full, text_length, extractor),
        )
        conn.commit()


def _store_layout(
    document_id: str,
    line_rows: list[tuple],
    span_rows: list[tuple],
) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM du_layout_spans WHERE document_id = ?", (document_id,))
        cur.execute("DELETE FROM du_layout_lines WHERE document_id = ?", (document_id,))

        if span_rows:
            cur.executemany(
                """
                INSERT INTO du_layout_spans (
                    layout_span_id,
                    document_id,
                    page_index,
                    block_no,
                    line_no,
                    span_no,
                    reading_order,
                    text,
                    x0,
                    y0,
                    x1,
                    y1,
                    page_width,
                    page_height,
                    font_name,
                    font_size,
                    font_flags,
                    is_bold,
                    is_italic
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                span_rows,
            )

        if line_rows:
            cur.executemany(
                """
                INSERT INTO du_layout_lines (
                    layout_line_id,
                    document_id,
                    page_index,
                    block_no,
                    line_no,
                    reading_order,
                    text,
                    x0,
                    y0,
                    x1,
                    y1,
                    page_width,
                    page_height,
                    font_name,
                    font_size,
                    font_flags,
                    is_bold,
                    is_italic
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                line_rows,
            )
        conn.commit()


def extract_text_pymupdf(path: Path, document_id: str, force: bool = False) -> dict:
    if not force and already_extracted(document_id):
        return {
            "status": "skipped",
            "reason": "already_extracted",
            "nul_bytes_removed": 0,
            "text_length": None,
        }

    try:
        full_text_parts: list[str] = []
        span_rows: list[tuple] = []
        line_rows: list[tuple] = []
        reading_order = 0

        with fitz.open(path) as doc:
            for page_index, page in enumerate(doc):
                page_dict = page.get_text("dict")
                page_width = float(page.rect.width)
                page_height = float(page.rect.height)

                page_text = page.get_text("text") or ""
                full_text_parts.append(page_text)

                for block_no, block in enumerate(page_dict.get("blocks", [])):
                    if block.get("type") != 0:
                        continue

                    for line_no, line in enumerate(block.get("lines", [])):
                        spans = line.get("spans", [])
                        if not spans:
                            continue

                        clean_spans = []
                        span_boxes: list[tuple[float, float, float, float]] = []

                        dominant_len = -1
                        dominant_font_name = None
                        dominant_font_size = None
                        dominant_font_flags = None
                        dominant_bold = False
                        dominant_italic = False

                        for span_no, span in enumerate(spans):
                            raw_text = span.get("text") or ""
                            text, _ = _sanitize_text(raw_text)
                            if not text.strip():
                                continue

                            bbox = span.get("bbox")
                            if bbox and len(bbox) == 4:
                                x0, y0, x1, y1 = map(float, bbox)
                                span_boxes.append((x0, y0, x1, y1))
                            else:
                                x0 = y0 = x1 = y1 = None

                            font_name = span.get("font")
                            font_size = float(span.get("size")) if span.get("size") is not None else None
                            font_flags = int(span.get("flags")) if span.get("flags") is not None else None
                            is_bold, is_italic = _font_flags_to_style(font_flags)

                            if len(text) > dominant_len:
                                dominant_len = len(text)
                                dominant_font_name = font_name
                                dominant_font_size = font_size
                                dominant_font_flags = font_flags
                                dominant_bold = is_bold
                                dominant_italic = is_italic

                            span_rows.append(
                                (
                                    str(uuid.uuid4()),
                                    document_id,
                                    page_index,
                                    block_no,
                                    line_no,
                                    span_no,
                                    reading_order,
                                    text,
                                    x0,
                                    y0,
                                    x1,
                                    y1,
                                    page_width,
                                    page_height,
                                    font_name,
                                    font_size,
                                    font_flags,
                                    is_bold,
                                    is_italic,
                                )
                            )
                            clean_spans.append(text)
                            reading_order += 1

                        if not clean_spans:
                            continue

                        line_text = "".join(clean_spans).strip()
                        if not line_text:
                            continue

                        lx0, ly0, lx1, ly1 = _union_bbox(span_boxes)

                        line_rows.append(
                            (
                                str(uuid.uuid4()),
                                document_id,
                                page_index,
                                block_no,
                                line_no,
                                reading_order,
                                line_text,
                                lx0,
                                ly0,
                                lx1,
                                ly1,
                                page_width,
                                page_height,
                                dominant_font_name,
                                dominant_font_size,
                                dominant_font_flags,
                                dominant_bold,
                                dominant_italic,
                            )
                        )
                        reading_order += 1

        raw_text = "".join(full_text_parts)
        text, nul_count = _sanitize_text(raw_text)

        store_extraction(
            document_id=document_id,
            extractor="pymupdf",
            text_full=text,
            text_length=len(text),
            nul_bytes_removed=nul_count,
            extract_status="ok",
            extract_error=None,
        )

        _store_layout(
            document_id=document_id,
            line_rows=line_rows,
            span_rows=span_rows,
        )

        return {
            "status": "ok",
            "nul_bytes_removed": nul_count,
            "text_length": len(text),
            "layout_lines": len(line_rows),
            "layout_spans": len(span_rows),
        }

    except Exception as exc:
        store_extraction(
            document_id=document_id,
            extractor="pymupdf",
            text_full=None,
            text_length=None,
            nul_bytes_removed=0,
            extract_status="error",
            extract_error=f"{type(exc).__name__}: {exc}",
        )

        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "nul_bytes_removed": 0,
            "text_length": None,
        }
