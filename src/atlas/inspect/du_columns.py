from atlas.db.connection import get_connection
from atlas.document_understanding.persistence.repository import DURepository


def inspect_du_columns(limit=5):

    with get_connection() as conn:

        repo = DURepository(conn)

        docs = repo.fetch_documents()

        for document_id, path in docs[:limit]:

            with repo.conn.cursor() as cur:

                cur.execute(
                    """
                    select
                        b.page_index,
                        c.column_index,
                        b.block_index,
                        left(b.text,80)
                    from du_blocks b
                    join du_block_columns c
                    on c.block_id = b.block_id
                    where b.document_id = %s
                    order by b.page_index, c.column_index, b.block_index
                    """,
                    (document_id,),
                )

                rows = cur.fetchall()

            print("=" * 90)
            print(path)

            for r in rows[:30]:
                print(r)
