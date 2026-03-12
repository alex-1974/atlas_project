from __future__ import annotations

from atlas.db.connection import get_connection


def inspect_authors(limit: int = 200) -> None:
    query = """
        select
            d.relative_path,
            d.title,
            a.display_name,
            da.source,
            da.author_position,
            case
                when fm.region_id is not null then true
                else false
            end as has_front_matter,
            case
                when tp.region_id is not null then true
                else false
            end as has_title_page
        from document_authors da
        join authors a on a.author_id = da.author_id
        join documents d on d.document_id = da.document_id
        left join lateral (
            select region_id
            from document_regions
            where document_id = d.document_id
              and region_type = 'front_matter'
            order by region_index asc
            limit 1
        ) fm on true
        left join lateral (
            select region_id
            from document_regions
            where document_id = d.document_id
              and region_type = 'title_page'
            order by region_index asc
            limit 1
        ) tp on true
        order by
            d.relative_path,
            da.author_position nulls last,
            a.display_name
        limit %s
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (limit,))
            rows = cur.fetchall()

    last_path = None

    for path, title, name, source, pos, has_front_matter, has_title_page in rows:
        if path != last_path:
            print()
            print(path)
            print(f"  title        : {title or '-'}")
            print(
                "  regions      : "
                f"front_matter={'yes' if has_front_matter else 'no'}, "
                f"title_page={'yes' if has_title_page else 'no'}"
            )
            last_path = path

        pos_text = f"{pos:>2}" if pos is not None else " -"
        print(f"  {pos_text}  {name}  ({source})")
