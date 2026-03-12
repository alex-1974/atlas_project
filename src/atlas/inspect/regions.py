from __future__ import annotations

import typer

from atlas.db.connection import get_connection


def _compact(text: str | None, limit: int = 160) -> str:
    if not text:
        return "-"
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def get_document_regions(limit: int = 50) -> list[tuple]:
    """
    Return document regions for inspection.

    Output columns (stable contract):

    document_id
    relative_path
    region_index
    region_type
    start_char
    end_char
    char_length
    preview
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id,
                    d.relative_path,
                    r.region_index,
                    r.region_type,
                    r.start_char,
                    r.end_char,
                    (r.end_char - r.start_char) as char_length,
                    regexp_replace(r.text, '\\s+', ' ', 'g') as preview
                from document_regions r
                join documents d on d.document_id = r.document_id
                order by
                    d.relative_path,
                    r.region_index
                limit %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    formatted: list[tuple] = []

    for (
        document_id,
        path,
        region_index,
        region_type,
        start_char,
        end_char,
        char_length,
        preview,
    ) in rows:
        formatted.append(
            (
                document_id,
                path,
                region_index,
                region_type,
                start_char,
                end_char,
                char_length,
                _compact(preview),
            )
        )

    return formatted


def inspect_regions(limit: int = 100) -> None:
    """Print detected document regions."""
    rows = get_document_regions(limit=limit)

    if not rows:
        typer.echo("no regions")
        return

    current_path = None

    for (
        _document_id,
        relative_path,
        region_index,
        region_type,
        start_char,
        end_char,
        char_length,
        preview,
    ) in rows:
        if relative_path != current_path:
            if current_path is not None:
                typer.echo("")
            typer.echo(f"{relative_path}")
            typer.echo("-" * min(len(str(relative_path)), 80))
            current_path = relative_path

        typer.echo(
            f"[{region_index}] {region_type:20} "
            f"chars {start_char:6}-{end_char:<6} "
            f"len {char_length:6} {preview}"
        )
