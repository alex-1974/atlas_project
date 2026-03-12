from __future__ import annotations

from atlas.db.connection import get_connection
from atlas.structure.header_parse import parse_header
from atlas.structure.document_kind import score_document_kind


def _one_line(text: str, limit: int = 120) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def inspect_header(limit: int = 20) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.relative_path,
                    coalesce(fm.text, tp.text, e.text_full) as source_text,
                    case
                        when fm.text is not null then 'front_matter'
                        when tp.text is not null then 'title_page'
                        else 'full_text'
                    end as source_region,
                    d.title
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
                order by d.relative_path
                limit %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    for path, source_text, source_region, title in rows:
        text = str(source_text)
        parsed = parse_header(text, max_lines=40)
        kind = score_document_kind(text)
        best_kind, best_score = kind.best_kind()

        print(path)
        print(f"  stored title : {title or '-'}")
        print(f"  source region: {source_region}")
        print(f"  header lines : {len(parsed.lines)}")
        print(f"  document kind: {best_kind} ({best_score:.2f})")
        print(
            "  kind scores  : "
            f"article={kind.article_like:.2f}, "
            f"magazine={kind.magazine_article_like:.2f}, "
            f"thesis={kind.thesis_like:.2f}, "
            f"report={kind.report_like:.2f}, "
            f"teaching={kind.teaching_material_like:.2f}, "
            f"chapter={kind.book_chapter_like:.2f}, "
            f"toc={kind.toc_document_like:.2f}"
        )

        if parsed.lines:
            print("  header preview:")
            for item in parsed.lines[:5]:
                print(f"    [{item.line_index}] {_one_line(item.text)}")
        else:
            print("  header preview: -")

        if parsed.affiliation_lines:
            print("  affiliations:")
            for item in parsed.affiliation_lines[:3]:
                print(f"    [{item.line_index}] {_one_line(item.text)}")

        if parsed.date_lines:
            print("  dates:")
            for item in parsed.date_lines[:3]:
                print(f"    [{item.line_index}] {_one_line(item.text)}")

        if parsed.journal_lines:
            print("  journal lines:")
            for item in parsed.journal_lines[:3]:
                print(f"    [{item.line_index}] {_one_line(item.text)}")

        print()
