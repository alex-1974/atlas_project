from __future__ import annotations

import re

from atlas.document_understanding.persistence.repository import Repository


NUMBER_RE = re.compile(r"^\d+(\.\d+)*")
BULLET_RE = re.compile(r"^[•\-–*]")


def compute_surface_features(repo: Repository, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)

    if not blocks:
        return

    lengths = [len(b["text"]) for b in blocks if b["text"]]
    median_len = sorted(lengths)[len(lengths) // 2] if lengths else 80

    rows = []

    for b in blocks:
        text = (b["text"] or "").strip()

        if not text:
            continue

        word_count = len(text.split())

        rows.append(
            {
                "block_id": b["block_id"],
                "size_ratio": (len(text) / median_len) if median_len else 1.0,
                "is_all_caps": text.isupper(),
                "word_count": word_count,
                "ends_with_period": text.endswith("."),
                "starts_with_number": bool(NUMBER_RE.match(text)),
                "starts_with_bullet": bool(BULLET_RE.match(text)),
                "line_width_ratio": min(len(text) / 120.0, 1.0),
                "is_short_line": word_count <= 12,
            }
        )

    repo.insert_layout_features(rows)
