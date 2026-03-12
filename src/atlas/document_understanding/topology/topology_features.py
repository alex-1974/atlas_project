from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


def compute_topology(repo: DURepository, document_id: str) -> None:

    blocks = fetch_blocks(repo, document_id)

    if not blocks:
        return

    topology_rows = []

    for i, block in enumerate(blocks):

        prev_block = blocks[i - 1] if i > 0 else None
        next_block = blocks[i + 1] if i < len(blocks) - 1 else None

        is_first_on_page = True
        is_last_on_page = True

        if prev_block and prev_block["page_index"] == block["page_index"]:
            is_first_on_page = False

        if next_block and next_block["page_index"] == block["page_index"]:
            is_last_on_page = False

        topology_rows.append(
            {
                "block_id": block["block_id"],
                "prev_block_index": prev_block["block_index"] if prev_block else None,
                "next_block_index": next_block["block_index"] if next_block else None,
                "cluster_id": None,
                "early_block_rank": block["block_index"],
                "is_first_on_page": is_first_on_page,
                "is_last_on_page": is_last_on_page,
                "before_first_running_text": False,
                "after_toc_candidate": False,
                "repeated_header_footer_hint": False,
            }
        )

    insert_topology(repo, topology_rows)


def fetch_blocks(repo: DURepository, document_id):

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


def insert_topology(repo: DURepository, rows):

    with repo.conn.cursor() as cur:

        for r in rows:

            cur.execute(
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
                values (
                    %(block_id)s,
                    %(prev_block_index)s,
                    %(next_block_index)s,
                    %(cluster_id)s,
                    %(early_block_rank)s,
                    %(is_first_on_page)s,
                    %(is_last_on_page)s,
                    %(before_first_running_text)s,
                    %(after_toc_candidate)s,
                    %(repeated_header_footer_hint)s
                )
                on conflict (block_id) do nothing
                """,
                r,
            )
