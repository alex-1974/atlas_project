from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


COLUMN_GAP_SPLIT_RATIO = 0.18


@dataclass(slots=True, frozen=True)
class LayoutBlock:
    block_id: str
    block_index: int
    page_index: int
    text: str
    x0: float | None
    y0: float | None
    x1: float | None
    y1: float | None
    page_width: float | None
    page_height: float | None

    @property
    def center_x(self) -> float | None:
        if self.x0 is None or self.x1 is None:
            return None
        return (float(self.x0) + float(self.x1)) / 2.0


def _fetch_blocks(repo, document_id: str) -> list[LayoutBlock]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.block_index,
                b.page_index,
                b.text,
                b.x0,
                b.y0,
                b.x1,
                b.y1,
                p.width,
                p.height
            from du_blocks b
            left join du_pages p
              on p.document_id = b.document_id
             and p.page_index = b.page_index
            where b.document_id = %s
            order by b.page_index, b.block_index
            """,
            (document_id,),
        )
        rows = cur.fetchall()

    return [LayoutBlock(*row) for row in rows]


def _group_by_page(blocks: list[LayoutBlock]) -> dict[int, list[LayoutBlock]]:
    pages: dict[int, list[LayoutBlock]] = defaultdict(list)
    for block in blocks:
        pages[block.page_index].append(block)
    return dict(sorted(pages.items()))


def _fallback_column_assignment(page_blocks: list[LayoutBlock]) -> dict[str, int]:
    return {b.block_id: 0 for b in page_blocks}


def _detect_columns_for_page(page_blocks: list[LayoutBlock]) -> dict[str, int]:
    usable = [b for b in page_blocks if b.center_x is not None]
    if len(usable) < 3:
        return _fallback_column_assignment(page_blocks)

    usable = sorted(usable, key=lambda b: b.center_x)
    centers = [float(b.center_x) for b in usable]

    page_width = usable[0].page_width
    if page_width is None or page_width <= 0:
        return _fallback_column_assignment(page_blocks)

    gaps = [centers[i] - centers[i - 1] for i in range(1, len(centers))]
    if not gaps:
        return _fallback_column_assignment(page_blocks)

    max_gap = max(gaps)
    split_at = gaps.index(max_gap) + 1

    if max_gap < float(page_width) * COLUMN_GAP_SPLIT_RATIO:
        return _fallback_column_assignment(page_blocks)

    left_blocks = usable[:split_at]
    right_blocks = usable[split_at:]

    if not left_blocks or not right_blocks:
        return _fallback_column_assignment(page_blocks)

    mapping: dict[str, int] = {}
    for b in left_blocks:
        mapping[b.block_id] = 0
    for b in right_blocks:
        mapping[b.block_id] = 1
    for b in page_blocks:
        mapping.setdefault(b.block_id, 0)
    return mapping


def _sort_key(block: LayoutBlock) -> tuple[float, int]:
    if block.y0 is not None:
        return (float(block.y0), block.block_index)
    return (float(block.block_index), block.block_index)


def _compute_page_reading_order(page_blocks: list[LayoutBlock], column_map: dict[str, int]) -> list[LayoutBlock]:
    grouped: dict[int, list[LayoutBlock]] = defaultdict(list)
    for block in page_blocks:
        grouped[column_map.get(block.block_id, 0)].append(block)

    ordered: list[LayoutBlock] = []
    for column_index in sorted(grouped.keys()):
        ordered.extend(sorted(grouped[column_index], key=_sort_key))
    return ordered


def _persist_geometry_column_hints(repo, column_hints: dict[str, int]) -> None:
    rows = [(block_id, float(column_index)) for block_id, column_index in column_hints.items()]
    if not rows:
        return

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_geometry (block_id, column_hint)
            values (%s, %s)
            on conflict (block_id) do update
            set column_hint = excluded.column_hint,
                updated_at = now()
            """,
            rows,
        )
    repo.conn.commit()


def _persist_topology(repo, topology_rows: list[tuple]) -> None:
    if not topology_rows:
        return

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_topology (
                block_id,
                prev_block_index,
                next_block_index,
                cluster_id,
                early_block_rank,
                is_first_on_page,
                is_last_on_page,
                before_first_running_text,
                after_toc_candidate,
                repeated_header_footer_hint
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, false)
            on conflict (block_id) do update
            set
                prev_block_index = excluded.prev_block_index,
                next_block_index = excluded.next_block_index,
                cluster_id = excluded.cluster_id,
                early_block_rank = excluded.early_block_rank,
                is_first_on_page = excluded.is_first_on_page,
                is_last_on_page = excluded.is_last_on_page,
                before_first_running_text = excluded.before_first_running_text,
                after_toc_candidate = excluded.after_toc_candidate,
                repeated_header_footer_hint = false,
                updated_at = now()
            """,
            topology_rows,
        )
    repo.conn.commit()


def compute_layout_graph(repo, document_id: str) -> None:
    blocks = _fetch_blocks(repo, document_id)
    if not blocks:
        return

    pages = _group_by_page(blocks)

    all_column_hints: dict[str, int] = {}
    topology_rows: list[tuple] = []
    cluster_id_counter = 0

    for _, page_blocks in pages.items():
        column_map = _detect_columns_for_page(page_blocks)
        all_column_hints.update(column_map)

        ordered = _compute_page_reading_order(page_blocks, column_map)

        for i, block in enumerate(ordered):
            prev_block = ordered[i - 1] if i > 0 else None
            next_block = ordered[i + 1] if i + 1 < len(ordered) else None

            topology_rows.append(
                (
                    block.block_id,
                    prev_block.block_index if prev_block else None,
                    next_block.block_index if next_block else None,
                    cluster_id_counter + column_map.get(block.block_id, 0),
                    i,
                    i == 0,
                    i == len(ordered) - 1,
                    i == 0,
                    False,
                )
            )

        cluster_id_counter += max(column_map.values(), default=0) + 1

    _persist_geometry_column_hints(repo, all_column_hints)
    _persist_topology(repo, topology_rows)
