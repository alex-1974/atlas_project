from __future__ import annotations

from atlas.db.connection import get_connection
from atlas.document_understanding.persistence.repository import DURepository
from atlas.document_understanding.grammar.document_type import inspect_document_type


def inspect_du_document_type(limit: int = 20, path_filter: str | None = None) -> None:
    with get_connection() as conn:
        repo = DURepository(conn)
        docs = repo.fetch_documents()

        shown = 0

        for document_id, path in docs:
            if path_filter and path_filter.lower() not in str(path).lower():
                continue

            result = inspect_document_type(repo, document_id)

            print(
                f"{result['document_type']:18} "
                f"{result['block_count']:5d}  "
                f"{path}"
            )

            shown += 1
            if shown >= limit:
                break
