from __future__ import annotations

from atlas.document_understanding.core.models import (
    Block,
    DocumentContext,
    Page,
)
from atlas.document_understanding.persistence.repository import Repository
from atlas.document_understanding.segmentation.block_segmentation import (
    LayoutLine,
    induce_blocks_from_lines,
)


def _fetch_layout_lines(repo: Repository, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                page_index,
                reading_order,
                text,
                x0,
                y0,
                x1,
                y1,
                page_width,
                page_height,
                font_name,
                font_size,
                font_flags,
                is_bold,
                is_italic
            from du_layout_lines
            where document_id = %s
            order by page_index, reading_order
            """,
            (document_id,),
        )
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _group_by_page(lines: list[dict]) -> dict[int, list[LayoutLine]]:
    pages: dict[int, list[LayoutLine]] = {}

    for row in lines:
        line = LayoutLine(
            page_index=int(row["page_index"]),
            reading_order=int(row["reading_order"]),
            text=row["text"] or "",
            x0=row["x0"],
            y0=row["y0"],
            x1=row["x1"],
            y1=row["y1"],
            page_width=row["page_width"],
            page_height=row["page_height"],
            font_name=row.get("font_name"),
            font_size=row.get("font_size"),
            font_flags=row.get("font_flags"),
            is_bold=bool(row.get("is_bold") or False),
            is_italic=bool(row.get("is_italic") or False),
        )
        pages.setdefault(line.page_index, []).append(line)

    return dict(sorted(pages.items()))


def build_document_map(repo: Repository) -> None:
    docs = repo.fetch_documents()
    for doc in docs:
        build_document(repo, str(doc["document_id"]))


def build_document(repo: Repository, document_id: str) -> None:
    layout_lines_raw = _fetch_layout_lines(repo, document_id)
    if not layout_lines_raw:
        return

    layout_lines = _group_by_page(layout_lines_raw)

    ctx = DocumentContext(
        document_id=document_id,
        source_kind="pdf",
        text_source="pdf",
        geometry_source="pdf",
        reading_order_source="pdf",
        has_native_text=True,
        has_reliable_geometry=True,
        has_reliable_reading_order=True,
        text_confidence=1.0,
        geometry_confidence=1.0,
        reading_order_confidence=0.95,
    )
    repo.insert_document_context(ctx)

    pages: list[Page] = []
    all_blocks: list[Block] = []
    block_index = 0

    for page_index in sorted(layout_lines.keys()):
        page_rows = layout_lines[page_index]
        page_width = next((row.page_width for row in page_rows if row.page_width is not None), None)
        page_height = next((row.page_height for row in page_rows if row.page_height is not None), None)

        pages.append(
            Page(
                document_id=document_id,
                page_index=page_index,
                width=page_width,
                height=page_height,
                image_based=False,
                native_text_present=True,
                page_confidence=1.0,
            )
        )

        induced_blocks = induce_blocks_from_lines(page_rows)

        for induced in induced_blocks:
            all_blocks.append(
                Block(
                    document_id=document_id,
                    block_index=block_index,
                    page_index=page_index,
                    start_char=None,
                    end_char=None,
                    text=induced.text,
                    x0=induced.x0,
                    y0=induced.y0,
                    x1=induced.x1,
                    y1=induced.y1,
                    page_y0=induced.y0,
                    page_y1=induced.y1,
                    doc_y0=None,
                    doc_y1=None,
                    text_source="pdf",
                    geometry_source="pdf",
                    text_confidence=1.0,
                    geometry_confidence=1.0,
                    reading_order_confidence=0.9,
                )
            )
            block_index += 1

    repo.insert_pages(pages)
    repo.insert_blocks(all_blocks)
