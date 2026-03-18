# src/atlas/document_understanding/layers/context.py

from __future__ import annotations

from atlas.document_understanding.persistence.repository import Repository
from atlas.document_understanding.core.coordinate_system import (
    DocumentCoordinateSystem,
)


def _front_matter_score(y_ratio: float | None) -> float | None:
    if y_ratio is None:
        return None

    if y_ratio < 0.10:
        return 1.0

    if y_ratio < 0.20:
        return 0.8

    if y_ratio < 0.35:
        return 0.4

    return 0.0


def _back_matter_score(y_ratio: float | None) -> float | None:
    if y_ratio is None:
        return None

    if y_ratio > 0.85:
        return 1.0

    if y_ratio > 0.70:
        return 0.6

    if y_ratio > 0.55:
        return 0.3

    return 0.0


def _body_score(front: float | None, back: float | None) -> float | None:
    if front is None or back is None:
        return None

    return max(0.0, 1.0 - max(front, back))


def compute_context(repository: Repository, doc_id: int) -> None:
    """
    Compute document-position context signals for blocks.

    Adds:
        doc_y_ratio
        front_matter_score
        body_score
        back_matter_score
        page_top_ratio
    """

    blocks = repository.fetch_blocks(doc_id)

    if not blocks:
        return

    coord: DocumentCoordinateSystem = repository.fetch_coordinate_system(doc_id)

    rows = []

    for block in blocks:

        doc_y0 = block.get("doc_y0")
        page_y0 = block.get("y0")

        doc_y_ratio = coord.doc_y_ratio(doc_y0)
        page_y_ratio = coord.page_y_ratio(page_y0)

        front = _front_matter_score(doc_y_ratio)
        back = _back_matter_score(doc_y_ratio)
        body = _body_score(front, back)

        rows.append(
            {
                "block_id": block["block_id"],
                "doc_y_ratio": doc_y_ratio,
                "page_y_ratio": page_y_ratio,
                "front_matter_score": front,
                "body_score": body,
                "back_matter_score": back,
            }
        )

    repository.store_context_features(doc_id, rows)
