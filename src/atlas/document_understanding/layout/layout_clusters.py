# src/atlas/document_understanding/layout/layout_clusters.py
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


X_OVERLAP_MIN = 0.15
VERTICAL_GAP_MAX = 80.0
WIDTH_WIDE_RATIO = 0.75
WIDTH_NARROW_RATIO = 0.35


@dataclass(slots=True, frozen=True)
class ClusterBlock:
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
    column_hint: float | None

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


def _fetch_blocks(repo, document_id: str) -> list[ClusterBlock]:
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
                p.height as page_height,
                g.column_hint
            from du_blocks b
            left join du_pages p
              on p.document_id = b.document_id
             and p.page_index = b.page_index
            left join du_block_geometry g
              on g.block_id = b.block_id
            where b.document_id = %s
            order by b.page_index, b.block_index
            """,
            (document_id,),
        )
        rows = cur.fetchall()

    return [
        ClusterBlock(
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
            column_hint=row[10],
        )
        for row in rows
    ]


def _group_by_page(blocks: list[ClusterBlock]) -> dict[int, list[ClusterBlock]]:
    out: dict[int, list[ClusterBlock]] = defaultdict(list)
    for b in blocks:
        out[b.page_index].append(b)
    return dict(sorted(out.items()))


def _x_overlap_ratio(a: ClusterBlock, b: ClusterBlock) -> float:
    if a.x0 is None or a.x1 is None or b.x0 is None or b.x1 is None:
        return 0.0

    left = max(float(a.x0), float(b.x0))
    right = min(float(a.x1), float(b.x1))
    overlap = max(0.0, right - left)

    a_width = a.width or 0.0
    b_width = b.width or 0.0
    denom = min(a_width, b_width)
    if denom <= 0:
        return 0.0

    return overlap / denom


def _vertical_gap(a: ClusterBlock, b: ClusterBlock) -> float:
    if a.y1 is None or b.y0 is None:
        return float("inf")
    return float(b.y0) - float(a.y1)


def _same_column(a: ClusterBlock, b: ClusterBlock) -> bool:
    if a.column_hint is None or b.column_hint is None:
        return True
    return int(a.column_hint) == int(b.column_hint)


def _linked(a: ClusterBlock, b: ClusterBlock) -> bool:
    if a.page_index != b.page_index:
        return False

    if not _same_column(a, b):
        return False

    if _x_overlap_ratio(a, b) < X_OVERLAP_MIN:
        return False

    gap = _vertical_gap(a, b)
    if gap < -5.0:
        return False
    if gap > VERTICAL_GAP_MAX:
        return False

    return True


def _cluster_page(page_blocks: list[ClusterBlock]) -> list[list[ClusterBlock]]:
    if not page_blocks:
        return []

    ordered = sorted(
        page_blocks,
        key=lambda b: (
            int(b.column_hint) if b.column_hint is not None else 0,
            float(b.y0) if b.y0 is not None else float(b.block_index),
            b.block_index,
        ),
    )

    clusters: list[list[ClusterBlock]] = []
    current: list[ClusterBlock] = [ordered[0]]

    for block in ordered[1:]:
        if _linked(current[-1], block):
            current.append(block)
        else:
            clusters.append(current)
            current = [block]

    clusters.append(current)
    return clusters


def _cluster_bbox(cluster: list[ClusterBlock]) -> tuple[float | None, float | None, float | None, float | None]:
    xs0 = [float(b.x0) for b in cluster if b.x0 is not None]
    ys0 = [float(b.y0) for b in cluster if b.y0 is not None]
    xs1 = [float(b.x1) for b in cluster if b.x1 is not None]
    ys1 = [float(b.y1) for b in cluster if b.y1 is not None]

    return (
        min(xs0) if xs0 else None,
        min(ys0) if ys0 else None,
        max(xs1) if xs1 else None,
        max(ys1) if ys1 else None,
    )


def _cluster_kind(cluster: list[ClusterBlock]) -> str:
    sample = cluster[0]
    page_width = sample.page_width
    x0, y0, x1, y1 = _cluster_bbox(cluster)

    if page_width is None or x0 is None or x1 is None:
        return "text_cluster"

    width_ratio = (x1 - x0) / float(page_width)

    if width_ratio >= WIDTH_WIDE_RATIO:
        return "wide_cluster"
    if width_ratio <= WIDTH_NARROW_RATIO:
        return "narrow_cluster"

    distinct_columns = {
        int(b.column_hint) for b in cluster if b.column_hint is not None
    }
    if len(distinct_columns) >= 2:
        return "multi_column_cluster"

    return "text_cluster"


def _ensure_table(repo) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists du_layout_clusters (
                cluster_id bigserial primary key,
                document_id uuid not null references documents(document_id) on delete cascade,
                page_index integer not null,
                cluster_kind text not null,
                start_block_index integer not null,
                end_block_index integer not null,
                x0 real,
                y0 real,
                x1 real,
                y1 real,
                block_count integer not null,
                created_at timestamptz default now()
            )
            """
        )
        cur.execute(
            """
            create index if not exists idx_du_layout_clusters_doc_page
            on du_layout_clusters(document_id, page_index)
            """
        )
    repo.conn.commit()


def compute_layout_clusters(repo, document_id: str) -> None:
    _ensure_table(repo)

    blocks = _fetch_blocks(repo, document_id)
    if not blocks:
        return

    pages = _group_by_page(blocks)

    rows: list[tuple] = []

    for page_index, page_blocks in pages.items():
        clusters = _cluster_page(page_blocks)

        for cluster in clusters:
            x0, y0, x1, y1 = _cluster_bbox(cluster)
            rows.append(
                (
                    document_id,
                    page_index,
                    _cluster_kind(cluster),
                    min(b.block_index for b in cluster),
                    max(b.block_index for b in cluster),
                    x0,
                    y0,
                    x1,
                    y1,
                    len(cluster),
                )
            )

    with repo.conn.cursor() as cur:
        cur.execute("delete from du_layout_clusters where document_id = %s", (document_id,))
        cur.executemany(
            """
            insert into du_layout_clusters (
                document_id,
                page_index,
                cluster_kind,
                start_block_index,
                end_block_index,
                x0,
                y0,
                x1,
                y1,
                block_count
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    repo.conn.commit()
