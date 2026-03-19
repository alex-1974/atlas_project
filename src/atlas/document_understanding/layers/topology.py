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
                g.column_hint,
                g.page_y_ratio
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


def _same_columnish(a: dict, b: dict) -> float:
    ac = a.get("column_hint")
    bc = b.get("column_hint")
    if ac is None or bc is None:
        return 0.5
    return 1.0 if int(ac) == int(bc) else 0.0


def compute_topology(repo, document_id: str) -> None:
    blocks = _fetch_blocks(repo, document_id)
    if not blocks:
        return

    grouped = _group_by_page(blocks)

    rows: list[tuple] = []

    for page_index, page_blocks in grouped.items():
        page_count = len(page_blocks)

        for i, block in enumerate(page_blocks):
            prev_block = page_blocks[i - 1] if i > 0 else None
            next_block = page_blocks[i + 1] if i + 1 < len(page_blocks) else None

            same_page_prev = prev_block is not None
            same_page_next = next_block is not None
            page_transition_before = prev_block is None
            page_transition_after = next_block is None

            same_column_prev_like = _same_columnish(prev_block, block) if prev_block is not None else 0.0
            same_column_next_like = _same_columnish(block, next_block) if next_block is not None else 0.0

            column_index_candidate = int(block["column_hint"]) if block.get("column_hint") is not None else None
            odd_even_page = "odd" if (int(page_index) % 2 == 1) else "even"

            early_on_page_score = 1.0 - (i / max(1, page_count - 1)) if page_count > 1 else 1.0
            late_on_page_score = i / max(1, page_count - 1) if page_count > 1 else 1.0

            rows.append(
                (
                    block["block_id"],
                    same_page_prev,
                    same_page_next,
                    page_transition_before,
                    page_transition_after,
                    same_column_prev_like,
                    same_column_next_like,
                    column_index_candidate,
                    odd_even_page,
                    early_on_page_score,
                    late_on_page_score,
                )
            )

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_topology_signals (
                block_id,
                same_page_prev,
                same_page_next,
                page_transition_before,
                page_transition_after,
                same_column_prev_like,
                same_column_next_like,
                column_index_candidate,
                odd_even_page,
                early_on_page_score,
                late_on_page_score
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                same_page_prev = excluded.same_page_prev,
                same_page_next = excluded.same_page_next,
                page_transition_before = excluded.page_transition_before,
                page_transition_after = excluded.page_transition_after,
                same_column_prev_like = excluded.same_column_prev_like,
                same_column_next_like = excluded.same_column_next_like,
                column_index_candidate = excluded.column_index_candidate,
                odd_even_page = excluded.odd_even_page,
                early_on_page_score = excluded.early_on_page_score,
                late_on_page_score = excluded.late_on_page_score,
                updated_at = now()
            """,
            rows,
        )
    repo.conn.commit()
