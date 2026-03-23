from __future__ import annotations

from collections import defaultdict


def _fetch_blocks(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.page_index,
                b.block_index,
                b.x0,
                b.y0,
                b.x1,
                b.y1,
                g.column_hint,
                g.indent_left,
                g.indent_right,
                g.centeredness,
                g.whitespace_before,
                g.whitespace_after
            from du_blocks b
            left join du_block_geometry g on g.block_id = b.block_id
            where b.document_id = %s
            order by b.page_index, b.block_index
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


def _same_columnish(a: dict, b: dict) -> bool:
    ac = a.get("column_hint")
    bc = b.get("column_hint")
    if ac is None or bc is None:
        if a.get("x0") is None or b.get("x0") is None:
            return True
        return abs(float(a["x0"]) - float(b["x0"])) <= 40.0
    return int(ac) == int(bc)


def compute_spacing_rhythm(repo, document_id: str) -> None:
    blocks = _fetch_blocks(repo, document_id)
    if not blocks:
        return

    grouped = _group_by_page(blocks)

    all_gap_before = [row.get("whitespace_before") for row in blocks]
    all_gap_after = [row.get("whitespace_after") for row in blocks]
    median_before = _median(all_gap_before)
    median_after = _median(all_gap_after)

    rows: list[tuple] = []

    for _, page_blocks in grouped.items():
        for i, block in enumerate(page_blocks):
            prev_block = page_blocks[i - 1] if i > 0 else None
            next_block = page_blocks[i + 1] if i + 1 < len(page_blocks) else None

            line_gap_before = block.get("whitespace_before")
            line_gap_after = block.get("whitespace_after")

            paragraph_gap_before = None
            paragraph_gap_after = None

            if line_gap_before is not None and median_before is not None:
                paragraph_gap_before = float(line_gap_before) / max(1.0, float(median_before))

            if line_gap_after is not None and median_after is not None:
                paragraph_gap_after = float(line_gap_after) / max(1.0, float(median_after))

            indent_left = block.get("indent_left")
            indent_right = block.get("indent_right")

            centeredness = block.get("centeredness")
            alignment_center = 1.0 - min(1.0, float(centeredness)) if centeredness is not None else None
            alignment_left = 1.0 if (indent_left is not None and abs(float(indent_left)) < 10.0) else 0.0
            alignment_right = 1.0 if (indent_right is not None and abs(float(indent_right)) < 10.0) else 0.0

            continuation_like = 0.0
            break_like = 0.0

            if prev_block is not None and _same_columnish(prev_block, block):
                if line_gap_before is not None and median_before is not None and float(line_gap_before) <= float(median_before) * 1.25:
                    continuation_like += 0.5
                if indent_left is not None and abs(float(indent_left)) < 12.0:
                    continuation_like += 0.25
            else:
                break_like += 0.5

            if paragraph_gap_before is not None and paragraph_gap_before >= 1.6:
                break_like += 0.5

            if next_block is not None and not _same_columnish(block, next_block):
                break_like += 0.2

            continuation_like = min(1.0, continuation_like)
            break_like = min(1.0, break_like)

            rows.append(
                (
                    block["block_id"],
                    line_gap_before,
                    line_gap_after,
                    paragraph_gap_before,
                    paragraph_gap_after,
                    indent_left,
                    indent_right,
                    alignment_left,
                    alignment_center,
                    alignment_right,
                    continuation_like,
                    break_like,
                )
            )

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_spacing_rhythm (
                block_id,
                line_gap_before,
                line_gap_after,
                paragraph_gap_before,
                paragraph_gap_after,
                indent_left,
                indent_right,
                alignment_left,
                alignment_center,
                alignment_right,
                same_column_continuation_like,
                new_region_break_like
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                line_gap_before = excluded.line_gap_before,
                line_gap_after = excluded.line_gap_after,
                paragraph_gap_before = excluded.paragraph_gap_before,
                paragraph_gap_after = excluded.paragraph_gap_after,
                indent_left = excluded.indent_left,
                indent_right = excluded.indent_right,
                alignment_left = excluded.alignment_left,
                alignment_center = excluded.alignment_center,
                alignment_right = excluded.alignment_right,
                same_column_continuation_like = excluded.same_column_continuation_like,
                new_region_break_like = excluded.new_region_break_like,
                updated_at = now()
            """,
            rows,
        )
    repo.conn.commit()
