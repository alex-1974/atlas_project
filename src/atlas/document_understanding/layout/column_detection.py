from __future__ import annotations

from collections import defaultdict
from statistics import median

from atlas.document_understanding.persistence.repository import DURepository


COLUMN_SPLIT_THRESHOLD = 0.12


def fetch_block_geometry(repo: DURepository, document_id: str):

    with repo.conn.cursor() as cur:

        cur.execute(
            """
            select
                b.block_id,
                b.page_index,
                g.x0,
                g.x1,
                g.width
            from du_blocks b
            join du_block_geometry g
            on g.block_id = b.block_id
            where b.document_id = %s
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]

        return [dict(zip(cols, row)) for row in cur.fetchall()]


def group_by_page(blocks):

    pages = defaultdict(list)

    for b in blocks:
        pages[b["page_index"]].append(b)

    return pages


def detect_columns_for_page(blocks):

    if len(blocks) < 4:
        return {b["block_id"]: 0 for b in blocks}

    centers = [(b["x0"] + b["x1"]) / 2 for b in blocks]

    centers_sorted = sorted(centers)

    gaps = []

    for i in range(1, len(centers_sorted)):
        gaps.append(centers_sorted[i] - centers_sorted[i - 1])

    if not gaps:
        return {b["block_id"]: 0 for b in blocks}

    max_gap = max(gaps)
    med_gap = median(gaps)

    if max_gap < med_gap * 2:
        return {b["block_id"]: 0 for b in blocks}

    split_position = centers_sorted[gaps.index(max_gap) + 1]

    column_map = {}

    for b in blocks:

        center = (b["x0"] + b["x1"]) / 2

        if center < split_position:
            column_map[b["block_id"]] = 0
        else:
            column_map[b["block_id"]] = 1

    return column_map


def compute_columns(repo: DURepository, document_id: str):

    blocks = fetch_block_geometry(repo, document_id)

    pages = group_by_page(blocks)

    column_map = {}

    for page_blocks in pages.values():

        column_map.update(detect_columns_for_page(page_blocks))

    return column_map


def persist_columns(repo: DURepository, column_map):

    rows = [(k, v) for k, v in column_map.items()]

    with repo.conn.cursor() as cur:

        cur.executemany(
            """
            insert into du_block_columns
            (block_id, column_index)
            values (%s, %s)
            on conflict (block_id)
            do update set column_index = excluded.column_index
            """,
            rows,
        )

    repo.conn.commit()


def compute_and_store_columns(repo: DURepository, document_id: str):

    column_map = compute_columns(repo, document_id)

    persist_columns(repo, column_map)
