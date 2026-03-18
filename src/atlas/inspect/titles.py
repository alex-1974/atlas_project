from __future__ import annotations

import typer

from atlas.db.connection import get_connection


def _short(value: str | None, limit: int = 100) -> str:
    if not value:
        return "-"
    value = " ".join(str(value).split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def inspect_titles(limit: int = 80, review_only: bool = False) -> None:
    """
    Inspect stored document titles.

    Schema-safe version:
    only reads columns that are known to exist in the current DB.
    """

    query = """
        select
            relative_path,
            title,
            title_source
        from documents
        where title is not null
          and btrim(title) <> ''
        order by relative_path
        limit %s
    """

    params = (limit,)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    if not rows:
        typer.echo("no titles")
        return

    header = f"{'SOURCE':24} {'PATH':45} TITLE"
    typer.echo(header)
    typer.echo("-" * len(header))

    for relative_path, title, title_source in rows:
        path_short = _short(relative_path, 45)
        title_short = _short(title, 120)
        source_short = _short(title_source, 24)
        typer.echo(f"{source_short:24} {path_short:45} {title_short}")
