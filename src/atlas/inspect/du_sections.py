from __future__ import annotations

from atlas.db.connection import get_connection
from atlas.document_understanding.persistence.repository import DURepository
from atlas.document_understanding.sections.section_tree_builder import (
    build_section_tree,
    print_tree,
)


def inspect_du_sections(limit: int = 5, path_filter: str | None = None) -> None:
    with get_connection() as conn:
        repo = DURepository(conn)
        docs = repo.fetch_documents()

        shown = 0

        for document_id, path in docs:
            if path_filter and path_filter.lower() not in str(path).lower():
                continue

            with repo.conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        s.level,
                        s.title
                    from du_section_tree s
                    join du_blocks b
                        on b.block_id = s.block_id
                    where s.document_id = %s
                    order by b.page_index, b.block_index
                    """,
                    (document_id,),
                )
                rows = cur.fetchall()

            print("=" * 80)
            print(path)

            if not rows:
                shown += 1
                if shown >= limit:
                    break
                continue

            print("-- raw section rows --")
            raw_titles: list[str] = []

            for level, title in rows:
                indent = "  " * int(level)
                title = (title or "").strip()
                print(f"{indent}- {title}")
                if title:
                    raw_titles.append(title)

            print("-- reconstructed tree --")
            tree = build_section_tree(raw_titles)

            if tree:
                print_tree(tree)
            else:
                print("(no numbered section tree reconstructed)")

            shown += 1
            if shown >= limit:
                break
