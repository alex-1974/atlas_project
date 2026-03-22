# src/atlas/document_understanding/inference/headings.py

from __future__ import annotations
from typing import Any

from atlas.document_understanding.core.structural_sanity import (
    is_valid_heading_candidate,
    role_allows_heading,
    reject_by_roles,
)
from atlas.document_understanding.inference.document_model import (
    build_document_model,
    style_key,
)


def compute_headings(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)
    roles = repo.fetch_block_roles(document_id)

    role_map = {r["block_id"]: r for r in roles}

    model = build_document_model(blocks)

    candidates = []

    for b in blocks:
        role = role_map.get(b["block_id"], {})

        text = (b.get("text") or "").strip()
        if not text:
            continue

        # --- STRUCTURAL SANITY ---
        if not is_valid_heading_candidate(b):
            continue

        if reject_by_roles(role):
            continue

        if not role_allows_heading(role):
            continue

        candidates.append({
            "block_id": b["block_id"],
            "heading_score": role.get("heading_score"),
            "level": model.get("heading_level_by_style", {}).get(
                style_key(b), 1
            ),
            "is_title": False,
        })

    repo.store_document_model(document_id, model)
    repo.store_heading_candidates(document_id, candidates)
