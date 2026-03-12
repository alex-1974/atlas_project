from __future__ import annotations

from atlas.db.connection import get_connection


def _fmt_float(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def inspect_titles(limit: int = 100, review_only: bool = False) -> None:
    query = """
        select
            relative_path,
            title,
            title_source,
            title_score_raw,
            title_confidence,
            title_score_margin,
            title_candidate_count,
            title_needs_review
        from documents
    """

    params: list[object] = []

    if review_only:
        query += " where coalesce(title_needs_review, false) = true"

    query += """
        order by
            coalesce(title_needs_review, false) desc,
            title_confidence asc nulls first,
            title_score_margin asc nulls first,
            relative_path
        limit %s
    """
    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    for (
        path,
        title,
        source,
        score,
        confidence,
        margin,
        candidate_count,
        needs_review,
    ) in rows:
        print(path)
        print("  title      :", title)
        print("  source     :", source)
        print("  score      :", _fmt_float(score))
        print("  confidence :", _fmt_float(confidence))
        print("  margin     :", _fmt_float(margin))
        print("  candidates :", candidate_count if candidate_count is not None else "-")
        print("  review     :", bool(needs_review))
        print()
