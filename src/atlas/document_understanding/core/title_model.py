# src/atlas/document_understanding/core/title_model.py

from __future__ import annotations
from typing import Any, List


def is_title_candidate(row: dict[str, Any], model: dict[str, Any]) -> bool:
    size = row.get("font_size") or 0
    centered = row.get("centeredness") or 0
    max_size = model.get("max_font_size") or 0

    return (
        size >= max_size - 0.25
        and centered >= 0.7
        and (row.get("doc_y_ratio") or 0) <= 0.25
    )


def merge_titles(candidates: List[dict], blocks: dict) -> List[dict]:
    merged = []
    buffer = []

    def flush():
        nonlocal buffer
        if not buffer:
            return
        if len(buffer) == 1:
            merged.append(buffer[0])
        else:
            merged.append({
                **buffer[0],
                "text": " ".join(b["text"] for b in buffer),
                "is_title": True,
                "level": 0,
            })
        buffer = []

    for c in candidates:
        if not c.get("is_title"):
            flush()
            merged.append(c)
            continue

        if not buffer:
            buffer = [c]
            continue

        prev = buffer[-1]

        if (
            c["page_index"] == prev["page_index"]
            and c["block_index"] == prev["block_index"] + 1
            and c["style_key"] == prev["style_key"]
        ):
            buffer.append(c)
        else:
            flush()
            buffer = [c]

    flush()
    return merged
