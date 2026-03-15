from __future__ import annotations

from atlas.db.connection import get_connection
from atlas.document_understanding.persistence.repository import DURepository
from atlas.document_understanding.roles.block_roles import inspect_roles


def _compact(text: str | None, limit: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def inspect_du_roles(limit: int = 5, path_filter: str | None = None) -> None:
    with get_connection() as conn:
        repo = DURepository(conn)
        docs = repo.fetch_documents()

        shown = 0

        for document_id, path in docs:
            if path_filter and path_filter.lower() not in str(path).lower():
                continue

            rows = inspect_roles(repo, document_id)

            if not rows:
                continue

            print("=" * 100)
            print(f"DOC: {path}")
            print("-" * 100)

            for row in rows[:25]:
                role = row["role"]
                score = row["score"]
                text = _compact(row["text"], 110)
                print(
                    f"[p{row['page_index']:02d} b{row['block_index']:03d}] "
                    f"{role:18} {score:5.2f}  {text}"
                )

            shown += 1
            if shown >= limit:
                break
