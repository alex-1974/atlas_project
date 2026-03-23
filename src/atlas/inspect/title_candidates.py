from __future__ import annotations

import typer

from atlas.db.connection import get_connection
from atlas.enrich.title_from_text import extract_title_from_lines
from atlas.structure.header_candidates import extract_header_candidates


def _short(value: str | None, limit: int = 120) -> str:
    if not value:
        return "-"
    value = " ".join(str(value).split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def inspect_title_candidates(
    limit: int = 20,
    review_only: bool = True,
    top_k: int = 3,
) -> None:
    """
    Schema-safe title candidate inspection.

    Recomputes title candidates from source text instead of reading
    non-existent diagnostics columns from documents.
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id,
                    d.relative_path,
                    d.title,
                    d.title_source,
                    coalesce(fm.text, tp.text, e.text_full) as source_text
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

    if not rows:
        typer.echo("no documents")
        return

    shown = 0

    for document_id, relative_path, stored_title, title_source, source_text in rows:
        candidates = extract_header_candidates(str(source_text))
        lines = candidates.title_lines[:40]
        result = extract_title_from_lines(lines)

        if not result:
            if review_only:
                continue
            typer.echo(relative_path)
            typer.echo("-" * min(len(str(relative_path)), 80))
            typer.echo("stored : " + _short(stored_title))
            typer.echo("source : " + _short(title_source, 40))
            typer.echo("top candidates: none")
            typer.echo("")
            shown += 1
            continue

        if review_only and not bool(result["needs_review"]):
            continue

        typer.echo(relative_path)
        typer.echo("-" * min(len(str(relative_path)), 80))
        typer.echo("stored : " + _short(stored_title))
        typer.echo("source : " + _short(title_source, 40))
        typer.echo(
            f"best   : {_short(result['title'])}  "
            f"score={result['score']:.2f}  "
            f"conf={result['confidence']:.2f}  "
            f"margin={result['margin']:.2f}  "
            f"review={bool(result['needs_review'])}"
        )

        scored_candidates = result.get("scored_candidates", [])[:top_k]
        for i, item in enumerate(scored_candidates, start=1):
            typer.echo(
                f"  [{i}] score={float(item['score']):.2f} "
                f"line={int(item['line_index'])} "
                f"{_short(str(item['text']))}"
            )

        typer.echo("")
        shown += 1

    if shown == 0:
        typer.echo("no candidate rows")
