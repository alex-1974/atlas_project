from __future__ import annotations

from atlas.models.records import DocumentHit
from atlas.search.lexical import search_segments


def search_documents(
    query: str,
    top_k: int = 10,
    segment_pool: int = 100,
) -> list[DocumentHit]:
    segment_hits = search_segments(query, top_k=segment_pool)

    grouped: dict[str, DocumentHit] = {}

    for hit in segment_hits:
        existing = grouped.get(hit.relative_path)
        snippet = " ".join(hit.segment_text.split())[:300]

        if existing is None or hit.score > existing.score:
            grouped[hit.relative_path] = DocumentHit(
                score=hit.score,
                relative_path=hit.relative_path,
                title=hit.title,
                best_snippet=snippet,
            )

    results = sorted(
        grouped.values(),
        key=lambda x: x.score,
        reverse=True,
    )

    return results[:top_k]
