from __future__ import annotations

from atlas.document_understanding.persistence.repository import Repository


def compute_topology(repo: Repository, document_id: str) -> None:

    blocks = fetch_blocks(repo, document_id)

    if not blocks:
        return

    rows = []

    block_count = len(blocks)

    for i, block in enumerate(blocks):

        prev_block = blocks[i - 1] if i > 0 else None
        next_block = blocks[i + 1] if i < block_count - 1 else None

        page_index = block["page_index"]

        is_first_on_page = True
        is_last_on_page = True

        if prev_block and prev_block["page_index"] == page_index:
            is_first_on_page = False

        if next_block and next_block["page_index"] == page_index:
            is_last_on_page = False

        rows.append(
            (
                block["block_id"],
                prev_block["block_index"] if prev_block else None,
                next_block["block_index"] if next_block else None,
                None,
                block["block_index"],
                is_first_on_page,
                is_last_on_page,
                False,
                False,
                False,
            )
        )

    insert_topology(repo, rows)


def fetch_blocks(repo: Repository, document_id):

    with repo.conn.cursor() as cur:

        cur.execute(
            """
            select block_id, block_index, page_index
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]

        return [dict(zip(cols, r)) for r in cur.fetchall()]


def insert_topology(repo: Repository, rows):

    if not rows:
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
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (block_id) do nothing
            """,
            rows,
        )
