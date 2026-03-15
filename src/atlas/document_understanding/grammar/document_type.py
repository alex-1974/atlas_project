from __future__ import annotations

from typing import Literal

from atlas.document_understanding.persistence.repository import DURepository


DocumentType = Literal[
    "journal_article",
    "report",
    "book_chapter",
    "teaching_material",
    "toc_or_index",
    "other",
]


def fetch_document_grammar_map(repo: DURepository, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.block_index,
                b.page_index,
                b.text,

                coalesce(s.running_text_like, 0.0) as running_text_like,
                coalesce(s.heading_like, 0.0) as heading_like,
                coalesce(s.toc_like, 0.0) as toc_like,
                coalesce(s.reference_like, 0.0) as reference_like,
                coalesce(s.caption_like, 0.0) as caption_like,

                coalesce(g.near_page_top, 0.0) as near_page_top,
                coalesce(g.near_page_bottom, 0.0) as near_page_bottom,

                coalesce(t.early_block_rank, b.block_index) as early_block_rank
            from du_blocks b
            left join du_block_signals s on s.block_id = b.block_id
            left join du_block_geometry g on g.block_id = b.block_id
            left join du_block_topology t on t.block_id = b.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _text(block: dict) -> str:
    return (block.get("text") or "").strip().lower()


def infer_document_type(blocks: list[dict]) -> DocumentType:
    if not blocks:
        return "other"

    first_80 = blocks[:80]
    late_blocks = blocks[int(len(blocks) * 0.6) :]

    has_abstract = any(
        _text(b).startswith(("abstract", "zusammenfassung", "summary"))
        for b in first_80
    )

    has_keywords = any(
        _text(b).startswith(("keywords", "key words", "schlagwörter", "schlüsselwörter"))
        for b in first_80
    )

    has_references_heading = any(
        _text(b).startswith(("references", "bibliography", "literatur", "literaturverzeichnis"))
        for b in late_blocks
    )

    has_appendix = any(
        _text(b).startswith(("appendix", "appendices", "anhang"))
        for b in late_blocks
    )

    toc_blocks = sum(1 for b in first_80 if float(b["toc_like"]) > 0.6)
    ref_blocks = sum(1 for b in late_blocks if float(b["reference_like"]) > 0.6)
    caption_blocks = sum(1 for b in blocks if float(b["caption_like"]) > 0.7)
    dense_blocks = sum(1 for b in blocks if float(b["running_text_like"]) > 0.6)
    heading_blocks = sum(1 for b in blocks if float(b["heading_like"]) > 0.6)

    # toc_or_index
    if toc_blocks >= 6 and dense_blocks < max(5, len(blocks) * 0.2):
        return "toc_or_index"

    # journal_article
    if has_abstract and has_references_heading:
        return "journal_article"
    if has_abstract and ref_blocks >= 5:
        return "journal_article"
    if has_keywords and ref_blocks >= 5:
        return "journal_article"

    # teaching_material
    if heading_blocks >= 8 and caption_blocks >= 2 and ref_blocks < 3:
        return "teaching_material"

    # report
    if toc_blocks >= 3 and dense_blocks >= 10:
        return "report"
    if has_appendix and dense_blocks >= 10:
        return "report"

    # book_chapter
    if dense_blocks >= 15 and ref_blocks >= 3 and not has_abstract:
        return "book_chapter"

    return "other"


def inspect_document_type(repo: DURepository, document_id: str) -> dict:
    blocks = fetch_document_grammar_map(repo, document_id)
    doc_type = infer_document_type(blocks)

    return {
        "document_type": doc_type,
        "block_count": len(blocks),
    }
