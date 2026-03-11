from __future__ import annotations

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from atlas.db.connection import get_connection


@dataclass
class SearchHit:
    score: float
    relative_path: str
    title: str
    segment_text: str


def _load_segments():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.relative_path,
                    coalesce(d.title, 'NO_TITLE') as title,
                    s.text
                from text_segments s
                join documents d on d.document_id = s.document_id
                where s.segment_type = 'paragraph'
                order by d.relative_path, s.segment_index
                """
            )
            return cur.fetchall()


def search_segments(query: str, top_k: int = 10) -> list[SearchHit]:
    rows = _load_segments()

    if not rows:
        return []

    docs = [row[2] for row in rows]

    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        max_features=50000,
        ngram_range=(1, 2),
    )

    matrix = vectorizer.fit_transform(docs)
    query_vec = vectorizer.transform([query])

    sims = cosine_similarity(query_vec, matrix).flatten()
    top_idx = sims.argsort()[::-1][:top_k]

    hits: list[SearchHit] = []
    for idx in top_idx:
        score = float(sims[idx])
        if score <= 0:
            continue

        relative_path, title, segment_text = rows[idx]
        hits.append(
            SearchHit(
                score=score,
                relative_path=relative_path,
                title=title,
                segment_text=segment_text,
            )
        )

    return hits
