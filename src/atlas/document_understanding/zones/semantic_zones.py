from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


SEMANTIC_MAPPING = {
    "header_candidate": "header",
    "toc_candidate": "toc",
    "references_candidate": "references",
    "body_candidate": "body",
}


def compute_semantic_zones(repo: DURepository, document_id: str) -> None:
    hypotheses = fetch_zone_hypotheses(repo, document_id)
    memberships = fetch_memberships(repo, document_id)

    if not hypotheses:
        return

    membership_map = build_membership_map(memberships)
    rows = []

    for h in hypotheses:
        candidate_type = h["zone_type"]
        semantic_type = SEMANTIC_MAPPING.get(candidate_type)

        if semantic_type is None:
            continue

        start_idx = h["start_block_index"]
        end_idx = h["end_block_index"]

        refined = refine_zone_bounds(
            candidate_type=candidate_type,
            start_idx=start_idx,
            end_idx=end_idx,
            membership_map=membership_map,
        )

        if refined is None:
            continue

        refined_start, refined_end, confidence = refined

        rows.append(
            {
                "document_id": document_id,
                "zone_type": semantic_type,
                "start_block_index": refined_start,
                "end_block_index": refined_end,
                "page_start": h["page_start"],
                "page_end": h["page_end"],
                "confidence": confidence,
                "source": "semantic_zones_v1",
            }
        )

    insert_semantic_zones(repo, rows)


def fetch_zone_hypotheses(repo: DURepository, document_id: str):
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                zone_type,
                start_block_index,
                end_block_index,
                page_start,
                page_end,
                score
            from du_zone_hypotheses
            where document_id = %s
            order by start_block_index, end_block_index
            """,
            (document_id,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_memberships(repo: DURepository, document_id: str):
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_index,
                m.zone_type,
                m.membership
            from du_block_zone_memberships m
            join du_blocks b on b.block_id = m.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def build_membership_map(rows):
    result: dict[str, dict[int, float]] = {}

    for r in rows:
        zone_type = r["zone_type"]
        block_index = r["block_index"]
        membership = r["membership"]

        if zone_type not in result:
            result[zone_type] = {}

        result[zone_type][block_index] = membership

    return result


def refine_zone_bounds(
    candidate_type: str,
    start_idx: int,
    end_idx: int,
    membership_map: dict[str, dict[int, float]],
):
    zone_memberships = membership_map.get(candidate_type, {})

    block_indices = [
        idx
        for idx in range(start_idx, end_idx + 1)
        if zone_memberships.get(idx, 0.0) >= 0.40
    ]

    if not block_indices:
        return None

    refined_start = min(block_indices)
    refined_end = max(block_indices)

    values = [zone_memberships.get(idx, 0.0) for idx in range(refined_start, refined_end + 1)]
    confidence = sum(values) / max(len(values), 1)

    return refined_start, refined_end, confidence


def insert_semantic_zones(repo: DURepository, rows) -> None:
    with repo.conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                insert into du_semantic_zones (
                    document_id,
                    zone_type,
                    start_block_index,
                    end_block_index,
                    page_start,
                    page_end,
                    confidence,
                    source
                )
                values (
                    %(document_id)s,
                    %(zone_type)s,
                    %(start_block_index)s,
                    %(end_block_index)s,
                    %(page_start)s,
                    %(page_end)s,
                    %(confidence)s,
                    %(source)s
                )
                """,
                r,
            )
