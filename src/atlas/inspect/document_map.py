from __future__ import annotations

from atlas.db.connection import get_connection
from atlas.document_understanding.persistence.repository import DURepository


def inspect_document_map(
    limit: int | None = None,
    document_path_filter: str | None = None,
) -> None:
    with get_connection() as conn:
        repo = DURepository(conn)

        docs = repo.fetch_documents()

        if document_path_filter:
            needle = document_path_filter.lower()
            docs = [
                (document_id, path)
                for document_id, path in docs
                if needle in str(path or "").lower()
            ]

        if limit:
            docs = docs[:limit]

        for document_id, path in docs:
            print()
            print(path or document_id)

            zones = fetch_semantic_zones(repo, document_id)
            blocks = fetch_blocks(repo, document_id)

            print("  semantic zones:")

            if not zones:
                print("    -")
            else:
                for z in zones:
                    conf = 0.0 if z["confidence"] is None else float(z["confidence"])
                    print(
                        f"    {z['zone_type']:<12} "
                        f"{z['start_block_index']}-{z['end_block_index']}    "
                        f"conf={conf:.2f}"
                    )

            print("  blocks:")

            if not blocks:
                print("    -")
            else:
                for b in blocks:
                    print(
                        f"    [{b['block_index']:>4}] "
                        f"p={b['page_index']}  "
                        f"T={b['title_like']:.2f} "
                        f"A={b['author_like']:.2f} "
                        f"Aff={b['affiliation_like']:.2f} "
                        f"D={b['date_like']:.2f} "
                        f"Run={b['running_text_like']:.2f} "
                        f"Hd={b['heading_like']:.2f} "
                        f"TOC={b['toc_like']:.2f} "
                        f"Ref={b['reference_like']:.2f} "
                        f"Cap={b['caption_like']:.2f} "
                        f"J={b['journal_meta_like']:.2f} "
                        f"Art={b['artifact_like']:.2f} "
                        f"Map={b['map_label_like']:.2f} "
                        f"N={b['noise_like']:.2f} "
                        f"Top={b['near_page_top']:.2f} "
                        f"HM={b['header_membership']:.2f} "
                        f"BM={b['body_membership']:.2f} "
                        f"TM={b['toc_membership']:.2f} "
                        f"RM={b['references_membership']:.2f}"
                    )

                    text_preview = (b["text"] or "").replace("\n", " ").strip()
                    if len(text_preview) > 90:
                        text_preview = text_preview[:90] + "…"

                    print(f"          {text_preview}")


def fetch_semantic_zones(repo: DURepository, document_id: str):
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                zone_type,
                start_block_index,
                end_block_index,
                confidence
            from du_semantic_zones
            where document_id = %s
            order by start_block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def fetch_blocks(repo: DURepository, document_id: str):
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_index,
                b.page_index,
                b.text,

                coalesce(s.title_like, 0.0) as title_like,
                coalesce(s.author_like, 0.0) as author_like,
                coalesce(s.affiliation_like, 0.0) as affiliation_like,
                coalesce(s.date_like, 0.0) as date_like,
                coalesce(s.running_text_like, 0.0) as running_text_like,
                coalesce(s.heading_like, 0.0) as heading_like,
                coalesce(s.toc_like, 0.0) as toc_like,
                coalesce(s.reference_like, 0.0) as reference_like,
                coalesce(s.caption_like, 0.0) as caption_like,
                coalesce(s.journal_meta_like, 0.0) as journal_meta_like,
                coalesce(s.artifact_like, 0.0) as artifact_like,
                coalesce(s.map_label_like, 0.0) as map_label_like,
                coalesce(s.noise_like, 0.0) as noise_like,

                coalesce(g.near_page_top, 0.0) as near_page_top,

                max(case when m.zone_type = 'header_candidate' then m.membership end) as header_membership,
                max(case when m.zone_type = 'body_candidate' then m.membership end) as body_membership,
                max(case when m.zone_type = 'toc_candidate' then m.membership end) as toc_membership,
                max(case when m.zone_type = 'references_candidate' then m.membership end) as references_membership

            from du_blocks b
            left join du_block_signals s
                on s.block_id = b.block_id
            left join du_block_geometry g
                on g.block_id = b.block_id
            left join du_block_zone_memberships m
                on m.block_id = b.block_id

            where b.document_id = %s
            group by
                b.block_index,
                b.page_index,
                b.text,
                s.title_like,
                s.author_like,
                s.affiliation_like,
                s.date_like,
                s.running_text_like,
                s.heading_like,
                s.toc_like,
                s.reference_like,
                s.caption_like,
                s.journal_meta_like,
                s.artifact_like,
                s.map_label_like,
                s.noise_like,
                g.near_page_top
            order by b.block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
