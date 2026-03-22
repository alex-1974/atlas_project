from __future__ import annotations


def _overlap(a: dict, b: dict) -> bool:
    return not (a["end_block_index"] < b["start_block_index"]
                or b["end_block_index"] < a["start_block_index"])


def _zone_strength(z: dict) -> float:
    length = z["end_block_index"] - z["start_block_index"] + 1
    return float(z.get("score", 0.0)) + 0.1 * length


def _resolve_conflicts(zones: list[dict]) -> list[dict]:
    zones_sorted = sorted(zones, key=_zone_strength, reverse=True)
    result = []

    for z in zones_sorted:
        if not any(_overlap(z, r) for r in result):
            result.append(z)

    return sorted(result, key=lambda z: z["start_block_index"])


def compute_semantic_zones(repo, document_id: str) -> None:
    hypotheses = repo.fetch_zone_hypotheses(document_id)

    if not hypotheses:
        repo.store_semantic_zones(document_id, [])
        return

    zones = []
    for h in hypotheses:
        zones.append({
            "zone_type": h["zone_type"],
            "start_block_index": h["start_block_index"],
            "end_block_index": h["end_block_index"],
            "page_start": h.get("page_start"),
            "page_end": h.get("page_end"),
            "score": float(h.get("score") or 0.0),
            "source": "du.semantic_zones.v2"
        })

    resolved = _resolve_conflicts(zones)

    repo.store_semantic_zones(document_id, resolved)
