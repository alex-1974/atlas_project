from __future__ import annotations

import re
import uuid

from atlas.db.connection import get_connection


PARA_MIN_LENGTH = 40
PARAGRAPH_VERTICAL_GAP_FACTOR = 1.8
INLINE_WS_RE = re.compile(r"[ \t]+")


def _normalize_inline(text: str) -> str:
    text = text.replace("\x00", "")
    return INLINE_WS_RE.sub(" ", text).strip()


def _bbox_union(items: list[dict]) -> tuple[float | None, float | None, float | None, float | None]:
    xs0 = [row["x0"] for row in items if row["x0"] is not None]
    ys0 = [row["y0"] for row in items if row["y0"] is not None]
    xs1 = [row["x1"] for row in items if row["x1"] is not None]
    ys1 = [row["y1"] for row in items if row["y1"] is not None]

    if not xs0:
        return None, None, None, None

    return min(xs0), min(ys0), max(xs1), max(ys1)


def _fetch_layout_lines(document_id: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    page_index,
                    reading_order,
                    text,
                    x0,
                    y0,
                    x1,
                    y1,
                    page_width,
                    page_height
                from du_layout_lines
                where document_id = %s
                order by page_index, reading_order
                """,
                (document_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _group_by_page(lines: list[dict]) -> dict[int, list[dict]]:
    pages: dict[int, list[dict]] = {}
    for row in lines:
        pages.setdefault(int(row["page_index"]), []).append(row)
    return pages


def _line_gap(prev: dict, cur: dict) -> float | None:
    if prev.get("y1") is None or cur.get("y0") is None:
        return None
    return float(cur["y0"]) - float(prev["y1"])


def _same_columnish(prev: dict, cur: dict) -> bool:
    if prev.get("x0") is None or cur.get("x0") is None:
        return True
    return abs(float(prev["x0"]) - float(cur["x0"])) <= 40.0


def _build_paragraphs(page_lines: list[dict]) -> list[dict]:
    if not page_lines:
        return []

    paragraphs: list[list[dict]] = []
    current = [page_lines[0]]
    running_gaps: list[float] = []

    for line in page_lines[1:]:
        prev = current[-1]
        gap = _line_gap(prev, line)
        same_column = _same_columnish(prev, line)

        threshold = 18.0
        if running_gaps:
            threshold = max(12.0, (sum(running_gaps) / len(running_gaps)) * PARAGRAPH_VERTICAL_GAP_FACTOR)

        split = False
        if not same_column:
            split = True
        elif gap is not None and gap > threshold:
            split = True
        elif prev["text"].rstrip().endswith((".", "!", "?")) and gap is not None and gap > 8.0:
            split = True

        if split:
            paragraphs.append(current)
            current = [line]
        else:
            current.append(line)
            if gap is not None and gap >= 0:
                running_gaps.append(gap)

    paragraphs.append(current)

    out: list[dict] = []
    for para_lines in paragraphs:
        text = _normalize_inline(" ".join(line["text"] for line in para_lines))
        if len(text) < PARA_MIN_LENGTH:
            continue

        x0, y0, x1, y1 = _bbox_union(para_lines)

        out.append(
            {
                "page_index": para_lines[0]["page_index"],
                "text": text,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "page_width": para_lines[0].get("page_width"),
                "page_height": para_lines[0].get("page_height"),
            }
        )

    return out


def segment_documents(force: bool = False) -> int:
    created = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute("delete from text_segments where segment_type = 'paragraph'")

            cur.execute(
                """
                select distinct document_id
                from du_layout_lines
                where not exists (
                    select 1
                    from text_segments s
                    where s.document_id = du_layout_lines.document_id
                      and s.segment_type = 'paragraph'
                )
                or %s = true
                order by document_id
                """,
                (force,),
            )
            doc_ids = [row[0] for row in cur.fetchall()]

        with conn.cursor() as cur:
            for document_id in doc_ids:
                lines = _fetch_layout_lines(document_id)
                if not lines:
                    continue

                pages = _group_by_page(lines)
                global_segment_index = 0

                for page_index in sorted(pages.keys()):
                    paragraphs = _build_paragraphs(pages[page_index])

                    for para in paragraphs:
                        cur.execute(
                            """
                            insert into text_segments (
                                segment_id,
                                document_id,
                                page_index,
                                segment_index,
                                segment_type,
                                text,
                                char_length,
                                x0,
                                y0,
                                x1,
                                y1,
                                page_width,
                                page_height
                            )
                            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                str(uuid.uuid4()),
                                document_id,
                                para["page_index"],
                                global_segment_index,
                                "paragraph",
                                para["text"],
                                len(para["text"]),
                                para["x0"],
                                para["y0"],
                                para["x1"],
                                para["y1"],
                                para["page_width"],
                                para["page_height"],
                            ),
                        )
                        global_segment_index += 1
                        created += 1

        conn.commit()

    return created
