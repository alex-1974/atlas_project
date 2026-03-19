from __future__ import annotations

from atlas.document_understanding.core.coordinate_system import safe_ratio


def compute_context(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    if not blocks:
        return

    doc_y1_values = [b.get("doc_y1") for b in blocks if b.get("doc_y1") is not None]
    document_height = max(doc_y1_values) if doc_y1_values else None

    rows: list[dict] = []

    for block in blocks:
        page_height = block.get("page_height")
        page_y0 = block.get("page_y0")
        page_y1 = block.get("page_y1")
        doc_y0 = block.get("doc_y0")
        doc_y1 = block.get("doc_y1")

        page_center = None
        if page_y0 is not None and page_y1 is not None:
            page_center = (float(page_y0) + float(page_y1)) / 2.0

        doc_center = None
        if doc_y0 is not None and doc_y1 is not None:
            doc_center = (float(doc_y0) + float(doc_y1)) / 2.0

        page_y_ratio = safe_ratio(page_center, page_height)
        doc_y_ratio = safe_ratio(doc_center, document_height)

        front_score = 0.0
        body_score = 0.0
        back_score = 0.0

        if doc_y_ratio is not None:
            if doc_y_ratio <= 0.18:
                front_score = 1.0 - (doc_y_ratio / 0.18)
            elif doc_y_ratio >= 0.78:
                back_score = min(1.0, (doc_y_ratio - 0.78) / 0.22)
            else:
                body_score = 1.0

        rows.append(
            {
                "block_id": block["block_id"],
                "doc_y_ratio": doc_y_ratio,
                "page_y_ratio": page_y_ratio,
                "front_matter_score": front_score,
                "body_score": body_score,
                "back_matter_score": back_score,
            }
        )

    repo.store_context_features(document_id, rows)
