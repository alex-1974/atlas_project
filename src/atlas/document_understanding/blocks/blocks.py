from __future__ import annotations

from atlas.document_understanding.models import (
    DocumentContext,
    Page,
    Block,
)

from atlas.document_understanding.persistence.repository import DURepository
from atlas.document_understanding.blocks.block_segmentation import segment_page_into_blocks


def build_document_map(repo: DURepository) -> None:
    docs = repo.fetch_documents()

    for document_id, path in docs:
        build_document(repo, document_id)


def build_document(repo: DURepository, document_id: str) -> None:

    segments = repo.fetch_text_segments(document_id)

    if not segments:
        return

    ctx = DocumentContext(
        document_id=document_id,
        source_kind="unknown",
        text_source="unknown",
        geometry_source="unknown",
        reading_order_source="unknown",
    )

    repo.insert_document_context(ctx)

    # ---------------------------------------------------------
    # Pages (einfach aus Segments ableiten)
    # ---------------------------------------------------------

    pages = []
    seen_pages = set()

    for page_index, segment_index, text in segments:
        if page_index not in seen_pages:
            seen_pages.add(page_index)

            pages.append(
                Page(
                    document_id=document_id,
                    page_index=page_index,
                    width=None,
                    height=None,
                    image_based=None,
                    native_text_present=True,
                    page_confidence=None,
                )
            )

    repo.insert_pages(pages)

    # ---------------------------------------------------------
    # Blocks
    # ---------------------------------------------------------

    block_index = 0
    current_page = None
    page_lines: list[str] = []

    def flush_page(page_index: int, lines: list[str]):
        nonlocal block_index

        if not lines:
            return

        page_text = "\n\n".join(lines)

        du_blocks = segment_page_into_blocks(page_text)

        page_blocks = []

        for text in du_blocks:

            page_blocks.append(
                Block(
                    document_id=document_id,
                    block_index=block_index,
                    page_index=page_index,
                    start_char=None,
                    end_char=None,
                    text=text,
                    x0=None,
                    y0=None,
                    x1=None,
                    y1=None,
                    page_y0=None,
                    page_y1=None,
                    doc_y0=None,
                    doc_y1=None,
                    text_source="unknown",
                    geometry_source="unknown",
                    text_confidence=None,
                    geometry_confidence=None,
                    reading_order_confidence=None,
                )
            )

            block_index += 1

        repo.insert_blocks(page_blocks)

    for page_index, segment_index, text in segments:

        if current_page is None:
            current_page = page_index

        if page_index != current_page:
            flush_page(current_page, page_lines)
            page_lines = []
            current_page = page_index

        if text:
            page_lines.append(text)

    flush_page(current_page, page_lines)
