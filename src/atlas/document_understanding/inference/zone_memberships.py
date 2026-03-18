from __future__ import annotations


ZONE_TITLE_PAGE = "title_page"
ZONE_ABSTRACT = "abstract"
ZONE_TOC = "toc"
ZONE_BODY = "body"
ZONE_REFERENCES = "references"
ZONE_APPENDIX = "appendix"
ZONE_FRONT_MATTER = "front_matter"
ZONE_BACK_MATTER = "back_matter"


def compute_zone_memberships(repo, document_id: str) -> None:

    # -----------------------------
    # load blocks + roles
    # -----------------------------

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.page_index,
                b.block_index,
                r.role
            from du_blocks b
            join du_block_roles r
                on r.block_id = b.block_id
            where b.document_id = %s
            order by b.page_index, b.block_index
            """,
            (document_id,),
        )
        blocks = cur.fetchall()

    # -----------------------------
    # load zone hypotheses
    # span-based schema:
    #   zone_type, start_block_index, end_block_index, score
    # -----------------------------

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
        rows = cur.fetchall()

    hypotheses_by_block_index: dict[int, list[tuple[str, float]]] = {}

    for zone_type, start_idx, end_idx, score in rows:
        if start_idx is None or end_idx is None:
            continue
        for block_index in range(int(start_idx), int(end_idx) + 1):
            hypotheses_by_block_index.setdefault(block_index, []).append(
                (zone_type, float(score or 0.0))
            )

    # -----------------------------
    # propagation engine
    # -----------------------------

    memberships = []
    current_zone = None

    for block_id, page_index, block_index, role in blocks:

        if block_index in hypotheses_by_block_index:
            best_zone = max(
                hypotheses_by_block_index[block_index],
                key=lambda x: x[1],
            )[0]
            current_zone = best_zone

        if role == "heading":
            if current_zone in (
                ZONE_ABSTRACT,
                ZONE_REFERENCES,
                ZONE_APPENDIX,
                ZONE_TOC,
            ):
                pass
            else:
                current_zone = ZONE_BODY

        if current_zone is None:
            if page_index <= 1:
                current_zone = ZONE_FRONT_MATTER
            else:
                current_zone = ZONE_BODY

        memberships.append(
            (
                block_id,
                current_zone,
                1.0,
                "inference.zone_memberships",
            )
        )

    # -----------------------------
    # write memberships
    # actual table is source-based, not zone_label/confidence-only
    # -----------------------------

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            delete from du_block_zone_memberships
            where block_id in (
                select block_id
                from du_blocks
                where document_id = %s
            )
            """,
            (document_id,),
        )

        cur.executemany(
            """
            insert into du_block_zone_memberships
            (
                block_id,
                zone_type,
                membership,
                source
            )
            values (%s, %s, %s, %s)
            """,
            memberships,
        )

    repo.conn.commit()
