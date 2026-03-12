from __future__ import annotations

from atlas.db.connection import get_connection
from atlas.enrich.title_from_text import extract_title_from_lines


def _fmt_float(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _one_line(text: str, limit: int = 140) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def inspect_title_candidates(limit: int = 20, review_only: bool = True, top_k: int = 3) -> None:
    where_extra = "and coalesce(d.title_needs_review, false) = true" if review_only else ""
    top_k = max(1, int(top_k))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    d.relative_path,
                    coalesce(fm.text, tp.text, e.text_full) as source_text,
                    case
                        when fm.text is not null then 'front_matter'
                        when tp.text is not null then 'title_page'
                        else 'full_text'
                    end as source_region,
                    d.title,
                    d.title_source,
                    d.title_score_raw,
                    d.title_confidence,
                    d.title_score_margin,
                    d.title_candidate_count,
                    d.title_needs_review
                from documents d
                join lateral (
                    select text_full
                    from extracted_texts
                    where document_id = d.document_id
                      and extract_status = 'ok'
                    order by created_at desc
                    limit 1
                ) e on true
                left join lateral (
                    select text
                    from document_regions
                    where document_id = d.document_id
                      and region_type = 'front_matter'
                    order by region_index asc
                    limit 1
                ) fm on true
                left join lateral (
                    select text
                    from document_regions
                    where document_id = d.document_id
                      and region_type = 'title_page'
                    order by region_index asc
                    limit 1
                ) tp on true
                where e.text_full is not null
                  and btrim(e.text_full) <> ''
                  {where_extra}
                order by
                    coalesce(d.title_needs_review, false) desc,
                    d.title_confidence asc nulls first,
                    d.title_score_margin asc nulls first,
                    d.relative_path
                limit %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    for (
        path,
        source_text,
        source_region,
        current_title,
        current_source,
        current_score,
        current_confidence,
        current_margin,
        current_candidate_count,
        current_review,
    ) in rows:
        print(path)
        print("  stored title :", current_title if current_title else "-")
        print("  title source :", current_source if current_source else "-")
        print("  source region:", source_region)
        print("  score        :", _fmt_float(current_score))
        print("  confidence   :", _fmt_float(current_confidence))
        print("  margin       :", _fmt_float(current_margin))
        print("  candidates   :", current_candidate_count if current_candidate_count is not None else "-")
        print("  review       :", bool(current_review))

        lines = str(source_text).splitlines()
        non_empty_lines = [line for line in lines if line.strip()]
        print("  source lines :", len(non_empty_lines))
        print("  source preview:")
        if non_empty_lines:
            for preview_line in non_empty_lines[:3]:
                print(f"    {_one_line(preview_line)}")
        else:
            print("    -")

        result = extract_title_from_lines(lines)

        if not result:
            print("  extracted    : -")
            print("  top candidates: -")
            print()
            continue

        print("  extracted    :", result.get("title") or "-")
        print("  new score    :", _fmt_float(result.get("score")))
        print("  new conf.    :", _fmt_float(result.get("confidence")))
        print("  new margin   :", _fmt_float(result.get("margin")))
        print("  new review   :", bool(result.get("needs_review")))

        scored = result.get("scored_candidates", [])
        if not scored:
            print("  top candidates: -")
            print()
            continue

        print("  top candidates:")
        for rank, item in enumerate(scored[:top_k], start=1):
            line_index = item.get("line_index")
            text = item.get("text", "")
            raw_line = "-"
            if isinstance(line_index, int) and 0 <= line_index < len(lines):
                raw_line = _one_line(lines[line_index], limit=100)

            print(
                f"    [{rank}] score={item['score']:.2f} "
                f"line={line_index} text={text}"
            )
            print(f"         raw={raw_line}")
        print()
