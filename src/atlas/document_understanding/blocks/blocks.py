from __future__ import annotations

from collections import defaultdict

from atlas.document_understanding.models import (
    DocumentContext,
    Page,
    Block,
)

from atlas.document_understanding.persistence.repository import DURepository


def build_document_map(repo: DURepository) -> None:
    """
    Build the minimal Document Map for all documents.

    Fills:

        du_document_context
        du_pages
        du_blocks
    """

    docs = repo.fetch_documents()

    for document_id, path in docs:
        build_document(repo, document_id)


def build_document(repo: DURepository, document_id: str) -> None:

    segments = repo.fetch_text_segments(document_id)

    if not segments:
        return

    # ---------------------------------------------------------
    # Document Context (minimal first version)
    # ---------------------------------------------------------

    ctx = DocumentContext(
        document_id=document_id,
        source_kind="unknown",
        text_source="unknown",
        geometry_source="unknown",
        reading_order_source="unknown",
    )

    repo.insert_document_context(ctx)

    # ---------------------------------------------------------
    # Pages
    # ---------------------------------------------------------

    pages = {}
    page_segments = defaultdict(list)

    for page_index, segment_index, text in segments:
        page_segments[page_index].append((segment_index, text))

    page_objects = []

    for page_index in sorted(page_segments):

        page_objects.append(
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

    repo.insert_pages(page_objects)

    # ---------------------------------------------------------
    # Blocks
    # ---------------------------------------------------------

    blocks = []
    block_index = 0

    for page_index in sorted(page_segments):

        segments_on_page = sorted(page_segments[page_index])

        for segment_index, text in segments_on_page:

            blocks.append(
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

    repo.insert_blocks(blocks)
