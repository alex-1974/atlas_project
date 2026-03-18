# src/atlas/document_understanding/layout/layout_graph.py
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass


HEADER_BAND_RATIO = 0.12
FOOTER_BAND_RATIO = 0.10
REPEAT_TEXT_MIN_LEN = 3
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
    def width(self) -> float | None:
        if self.x0 is None or self.x1 is None:
            return None
        return float(self.x1) - float(self.x0)

    @property
    def height(self) -> float | None:
        if self.y0 is None or self.y1 is None:
            return None
        return float(self.y1) - float(self.y0)

    @property
    def center_x(self) -> float | None:
        if self.x0 is None or self.x1 is None:
            return None
        return (float(self.x0) + float(self.x1)) / 2.0

    @property
    def center_y(self) -> float | None:
        if self.y0 is None or self.y1 is None:
            return None
        return (float(self.y0) + float(self.y1)) / 2.0


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
                p.width as page_width,
                p.height as page_height
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

    return [
        LayoutBlock(
            block_id=row[0],
            block_index=row[1],
            page_index=row[2],
            text=row[3] or "",
            x0=row[4],
            y0=row[5],
            x1=row[6],
            y1=row[7],
            page_width=row[8],
            page_height=row[9],
        )
        for row in rows
    ]


def _group_by_page(blocks: list[LayoutBlock]) -> dict[int, list[LayoutBlock]]:
    pages: dict[int, list[LayoutBlock]] = defaultdict(list)
    for block in blocks:
        pages[block.page_index].append(block)
    return dict(sorted(pages.items()))


def _fallback_column_assignment(page_blocks: list[LayoutBlock]) -> dict[str, int]:
    return {b.block_id: 0 for b in page_blocks}


def _detect_columns_for_page(page_blocks: list[LayoutBlock]) -> dict[str, int]:
    """
    Cheap but robust 1/2-column detector.

    Uses x-center gaps on a page. If geometry is missing, falls back to one column.
    """
    usable = [b for b in page_blocks if b.center_x is not None]
    if len(usable) < 3:
        return _fallback_column_assignment(page_blocks)

    usable = sorted(usable, key=lambda b: b.center_x)
    centers = [float(b.center_x) for b in usable]

    page_width = usable[0].page_width
    if page_width is None or page_width <= 0:
        return _fallback_column_assignment(page_blocks)

    gaps: list[float] = []
    for i in range(1, len(centers)):
        gaps.append(centers[i] - centers[i - 1])

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


def _column_block_sort_key(block: LayoutBlock) -> tuple[float, int]:
    if block.y0 is not None:
        return (float(block.y0), block.block_index)
    return (float(block.block_index), block.block_index)


def _compute_page_reading_order(
    page_blocks: list[LayoutBlock],
    column_map: dict[str, int],
) -> list[LayoutBlock]:
    """
    Reading order:
    column 0 top→bottom, then column 1 top→bottom.
    """
    grouped: dict[int, list[LayoutBlock]] = defaultdict(list)
    for b in page_blocks:
        grouped[column_map.get(b.block_id, 0)].append(b)

    ordered: list[LayoutBlock] = []
    for column_index in sorted(grouped.keys()):
        ordered.extend(sorted(grouped[column_index], key=_column_block_sort_key))
    return ordered


def _normalized_text(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _collect_repeated_header_footer_hints(
    pages: dict[int, list[LayoutBlock]],
) -> dict[str, bool]:
    """
    Mark very likely repeated header/footer lines across pages.
    """
    counts: Counter[tuple[str, str]] = Counter()
    bands: dict[str, str] = {}

    for _page_index, page_blocks in pages.items():
        for b in page_blocks:
            page_height = b.page_height
            y0 = b.y0
            y1 = b.y1
            text = _normalized_text(b.text)

            if (
                page_height is None
                or y0 is None
                or y1 is None
                or len(text) < REPEAT_TEXT_MIN_LEN
            ):
                continue

            top_band = float(page_height) * HEADER_BAND_RATIO
            bottom_band = float(page_height) * (1.0 - FOOTER_BAND_RATIO)

            band = None
            if float(y1) <= top_band:
                band = "header"
            elif float(y0) >= bottom_band:
                band = "footer"

            if band is None:
                continue

            key = (band, text)
            counts[key] += 1
            bands[b.block_id] = band + "|" + text

    repeated: dict[str, bool] = {}
    for page_blocks in pages.values():
        for b in page_blocks:
            sig = bands.get(b.block_id)
            if sig is None:
                repeated[b.block_id] = False
                continue
            band, text = sig.split("|", 1)
            repeated[b.block_id] = counts[(band, text)] >= 2

    return repeated


def _persist_geometry_column_hints(
    repo,
    column_hints: dict[str, int],
) -> None:
    rows = [(block_id, float(column_index)) for block_id, column_index in column_hints.items()]

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


def _persist_topology(
    repo,
    topology_rows: list[tuple],
) -> None:
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
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                repeated_header_footer_hint = excluded.repeated_header_footer_hint
            """,
            topology_rows,
        )
    repo.conn.commit()


def compute_layout_graph(repo, document_id: str) -> None:
    """
    Compute:
    - page-wise columns
    - page reading order
    - repeated header/footer hints

    Persists results into existing DU tables:
    - du_block_geometry.column_hint
    - du_block_topology.*
    """
    blocks = _fetch_blocks(repo, document_id)
    if not blocks:
        return

    pages = _group_by_page(blocks)
    repeated_header_footer_hint = _collect_repeated_header_footer_hints(pages)

    all_column_hints: dict[str, int] = {}
    topology_rows: list[tuple] = []

    cluster_id_counter = 0

    for _page_index, page_blocks in pages.items():
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
                    repeated_header_footer_hint.get(block.block_id, False),
                )
            )

        cluster_id_counter += max(column_map.values(), default=0) + 1

    _persist_geometry_column_hints(repo, all_column_hints)
    _persist_topology(repo, topology_rows)
