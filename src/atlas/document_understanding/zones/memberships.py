from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


ZONE_TYPES = (
    "header_candidate",
    "toc_candidate",
    "references_candidate",
    "body_candidate",
)


def compute_memberships(repo: DURepository, document_id: str) -> None:
    blocks = fetch_blocks(repo, document_id)
    hypotheses = fetch_zone_hypotheses(repo, document_id)

    if not blocks:
        return

    hyp_map = build_hypothesis_map(hypotheses)

    rows = []

    for block in blocks:
        block_index = block["block_index"]

        memberships = {}

        for zone_type in ZONE_TYPES:
            memberships[zone_type] = membership_for_block(
                block_index,
                hyp_map.get(zone_type),
            )

        for zone_type, membership in memberships.items():
            rows.append(
                {
                    "block_id": block["block_id"],
                    "zone_type": zone_type,
                    "membership": membership,
                    "source": "memberships_v1",
                }
            )

    insert_memberships(repo, rows)


def fetch_blocks(repo: DURepository, document_id: str):
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select block_id, block_index
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_zone_hypotheses(repo: DURepository, document_id: str):
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
            """,
            (document_id,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def build_hypothesis_map(hypotheses):
    result = {}

    for h in hypotheses:
        zone_type = h["zone_type"]

        current = result.get(zone_type)

        if current is None or h["score"] > current["score"]:
            result[zone_type] = h

    return result


def membership_for_block(block_index: int, hypothesis: dict | None) -> float:
    if hypothesis is None:
        return 0.0

    start_idx = hypothesis["start_block_index"]
    end_idx = hypothesis["end_block_index"]
    score = hypothesis["score"]

    if start_idx > end_idx:
        return 0.0

    if start_idx <= block_index <= end_idx:
        return min(1.0, 0.6 + 0.4 * score)

    # soft fringe around the zone
    distance = min(abs(block_index - start_idx), abs(block_index - end_idx))

    if distance == 1:
        return min(0.45, 0.25 + 0.15 * score)

    if distance == 2:
        return min(0.25, 0.10 + 0.10 * score)

    if distance == 3:
        return 0.08

    return 0.0


def insert_memberships(repo: DURepository, rows) -> None:
    with repo.conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                insert into du_block_zone_memberships (
                    block_id,
                    zone_type,
                    membership,
                    source
                )
                values (
                    %(block_id)s,
                    %(zone_type)s,
                    %(membership)s,
                    %(source)s
                )
                on conflict (block_id, zone_type, source) do nothing
                """,
                r,
            )
