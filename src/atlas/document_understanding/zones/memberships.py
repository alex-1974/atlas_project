from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


ZONE_TYPES = (
    "header_candidate",
    "body_candidate",
    "toc_candidate",
    "references_candidate",
)

MEMBERSHIP_SOURCE = "memberships_v4_sparse"


def compute_memberships(repo: DURepository, document_id: str) -> None:
    blocks = fetch_blocks(repo, document_id)
    hypotheses = fetch_zone_hypotheses(repo, document_id)

    if not blocks:
        return

    index_to_block_id = {
        b["block_index"]: b["block_id"]
        for b in blocks
    }

    membership_map: dict[tuple[str, str], float] = {}

    for hypothesis in hypotheses:
        zone_type = hypothesis["zone_type"]
        if zone_type not in ZONE_TYPES:
            continue

        membership = float(hypothesis["score"] or 0.0)
        if membership <= 0.0:
            continue

        start_block_index = hypothesis["start_block_index"]
        end_block_index = hypothesis["end_block_index"]

        for block_index in range(start_block_index, end_block_index + 1):
            block_id = index_to_block_id.get(block_index)
            if block_id is None:
                continue

            key = (block_id, zone_type)
            prev = membership_map.get(key, 0.0)
            if membership > prev:
                membership_map[key] = membership

    rows = [
        (block_id, zone_type, membership, MEMBERSHIP_SOURCE)
        for (block_id, zone_type), membership in membership_map.items()
    ]

    insert_memberships(repo, document_id, rows)


def fetch_blocks(repo: DURepository, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                block_id,
                block_index
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_zone_hypotheses(repo: DURepository, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                zone_type,
                start_block_index,
                end_block_index,
                score
            from du_zone_hypotheses
            where document_id = %s
            order by start_block_index, end_block_index
            """,
            (document_id,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def insert_memberships(
    repo: DURepository,
    document_id: str,
    rows: list[tuple[str, str, float, str]],
) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            delete from du_block_zone_memberships
            where source = %s
              and block_id in (
                  select block_id
                  from du_blocks
                  where document_id = %s
              )
            """,
            (MEMBERSHIP_SOURCE, document_id),
        )

        if not rows:
            return

        cur.executemany(
            """
            insert into du_block_zone_memberships (
                block_id,
                zone_type,
                membership,
                source
            )
            values (%s, %s, %s, %s)
            """,
            rows,
        )
