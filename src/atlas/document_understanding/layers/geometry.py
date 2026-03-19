from __future__ import annotations

from collections import defaultdict


def _fetch_pages(repo, document_id: str) -> dict[int, dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select page_index, width, height
            from du_pages
            where document_id = %s
            order by page_index
            """,
            (document_id,),
        )
        return {
            int(row[0]): {"width": row[1], "height": row[2]}
            for row in cur.fetchall()
        }


def _fetch_blocks(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                block_id,
                page_index,
                block_index,
                x0,
                y0,
                x1,
                y1
            from du_blocks
            where document_id = %s
            order by page_index, block_index
            """,
            (document_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _group_by_page(rows: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        out[int(row["page_index"])].append(row)
    return dict(sorted(out.items()))


def _median(values: list[float | None]) -> float | None:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    return clean[len(clean) // 2]


def _safe_ratio(value: float | None, denom: float | None) -> float | None:
    if value is None or denom in (None, 0):
        return None
    return float(value) / float(denom)


def compute_geometry(repo, document_id: str) -> None:
    pages = _fetch_pages(repo, document_id)
    blocks = _fetch_blocks(repo, document_id)
    if not blocks:
        return

    page_offsets: dict[int, float] = {}
    running_doc_y = 0.0
    for page_index in sorted(pages.keys()):
        page_offsets[page_index] = running_doc_y
        page_height = float(pages[page_index]["height"] or 0.0)
        running_doc_y += page_height
    document_height = running_doc_y if running_doc_y > 0 else None

    grouped = _group_by_page(blocks)

    geom_rows: list[tuple] = []
    doc_coord_rows: list[tuple] = []

    for page_index, page_blocks in grouped.items():
        page_meta = pages.get(page_index, {})
        page_width = float(page_meta.get("width") or 0.0)
        page_height = float(page_meta.get("height") or 0.0)
        doc_offset = page_offsets.get(page_index, 0.0)

        median_left = _median([b["x0"] for b in page_blocks])
        median_right = _median([b["x1"] for b in page_blocks])

        for i, block in enumerate(page_blocks):
            x0 = float(block["x0"]) if block["x0"] is not None else None
            y0 = float(block["y0"]) if block["y0"] is not None else None
            x1 = float(block["x1"]) if block["x1"] is not None else None
            y1 = float(block["y1"]) if block["y1"] is not None else None

            width = (x1 - x0) if x0 is not None and x1 is not None else None
            height = (y1 - y0) if y0 is not None and y1 is not None else None
            center_x = (x0 + x1) / 2.0 if x0 is not None and x1 is not None else None
            center_y = (y0 + y1) / 2.0 if y0 is not None and y1 is not None else None

            prev_block = page_blocks[i - 1] if i > 0 else None
            next_block = page_blocks[i + 1] if i + 1 < len(page_blocks) else None

            whitespace_before = None
            whitespace_after = None
            if prev_block is not None and prev_block["y1"] is not None and y0 is not None:
                whitespace_before = y0 - float(prev_block["y1"])
            if next_block is not None and y1 is not None and next_block["y0"] is not None:
                whitespace_after = float(next_block["y0"]) - y1

            indent_left = (x0 - median_left) if x0 is not None and median_left is not None else None
            indent_right = (median_right - x1) if x1 is not None and median_right is not None else None

            centeredness = None
            if center_x is not None and page_width > 0:
                centeredness = abs(center_x - (page_width / 2.0)) / (page_width / 2.0)

            near_page_top = _safe_ratio(y0, page_height)
            near_page_bottom = _safe_ratio((page_height - y1) if y1 is not None else None, page_height)

            doc_y0 = doc_offset + y0 if y0 is not None else None
            doc_y1 = doc_offset + y1 if y1 is not None else None

            page_y_ratio = _safe_ratio(center_y, page_height)
            doc_center = (doc_y0 + doc_y1) / 2.0 if doc_y0 is not None and doc_y1 is not None else None
            doc_y_ratio = _safe_ratio(doc_center, document_height)

            width_ratio = _safe_ratio(width, page_width)
            height_ratio = _safe_ratio(height, page_height)
            left_margin = _safe_ratio(x0, page_width)
            right_margin = _safe_ratio((page_width - x1) if x1 is not None else None, page_width)

            full_width_like = bool(width_ratio is not None and width_ratio >= 0.72)
            narrow_width_like = bool(width_ratio is not None and width_ratio <= 0.38)

            geom_rows.append(
                (
                    block["block_id"],
                    width,
                    height,
                    center_x,
                    center_y,
                    whitespace_before,
                    whitespace_after,
                    indent_left,
                    indent_right,
                    centeredness,
                    None,
                    near_page_top,
                    near_page_bottom,
                    width_ratio,
                    height_ratio,
                    page_y_ratio,
                    doc_y_ratio,
                    left_margin,
                    right_margin,
                    full_width_like,
                    narrow_width_like,
                )
            )

            doc_coord_rows.append((doc_y0, doc_y1, block["block_id"]))

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_geometry (
                block_id,
                width,
                height,
                center_x,
                center_y,
                whitespace_before,
                whitespace_after,
                indent_left,
                indent_right,
                centeredness,
                column_hint,
                near_page_top,
                near_page_bottom,
                width_ratio,
                height_ratio,
                page_y_ratio,
                doc_y_ratio,
                left_margin,
                right_margin,
                full_width_like,
                narrow_width_like
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                width = excluded.width,
                height = excluded.height,
                center_x = excluded.center_x,
                center_y = excluded.center_y,
                whitespace_before = excluded.whitespace_before,
                whitespace_after = excluded.whitespace_after,
                indent_left = excluded.indent_left,
                indent_right = excluded.indent_right,
                centeredness = excluded.centeredness,
                column_hint = coalesce(du_block_geometry.column_hint, excluded.column_hint),
                near_page_top = excluded.near_page_top,
                near_page_bottom = excluded.near_page_bottom,
                width_ratio = excluded.width_ratio,
                height_ratio = excluded.height_ratio,
                page_y_ratio = excluded.page_y_ratio,
                doc_y_ratio = excluded.doc_y_ratio,
                left_margin = excluded.left_margin,
                right_margin = excluded.right_margin,
                full_width_like = excluded.full_width_like,
                narrow_width_like = excluded.narrow_width_like,
                updated_at = now()
            """,
            geom_rows,
        )

        cur.executemany(
            """
            update du_blocks
            set doc_y0 = %s,
                doc_y1 = %s
            where block_id = %s
            """,
            doc_coord_rows,
        )

    repo.conn.commit()
