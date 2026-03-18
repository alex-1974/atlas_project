from __future__ import annotations


MIN_ZONE_LENGTH = 3  # minimale Blocklänge


def _length(z):
    return z["end_block_index"] - z["start_block_index"] + 1


def _merge_adjacent(zones):
    if not zones:
        return zones

    merged = [zones[0]]

    for z in zones[1:]:
        last = merged[-1]

        if z["zone_type"] == last["zone_type"]:
            last["end_block_index"] = z["end_block_index"]
            continue

        merged.append(z)

    return merged


def _absorb_small_zones(zones):
    """
    Entfernt kurze Inseln:
    A B A → A A A
    """

    if len(zones) < 3:
        return zones

    result = [zones[0]]

    for i in range(1, len(zones) - 1):
        prev = result[-1]
        curr = zones[i]
        nxt = zones[i + 1]

        if (
            _length(curr) < MIN_ZONE_LENGTH
            and prev["zone_type"] == nxt["zone_type"]
        ):
            # absorb into prev
            prev["end_block_index"] = nxt["end_block_index"]
            continue

        result.append(curr)

    result.append(zones[-1])
    return result


def _enforce_body_default(zones):
    """
    Body ist Default – aber:
    - front_matter am Anfang behalten
    - back_matter nur wenn keine klare Struktur
    """

    if not zones:
        return zones

    first_body_seen = False

    for i, z in enumerate(zones):
        t = z["zone_type"]

        # echte Spezialzonen behalten
        if t in ("title_page", "abstract", "toc", "references", "appendix"):
            continue

        if t == "body":
            first_body_seen = True
            continue

        if t == "front_matter":
            # vor erstem body behalten
            if not first_body_seen:
                continue
            # sonst → body
            z["zone_type"] = "body"
            continue

        if t == "back_matter":
            # optional später smarter
            z["zone_type"] = "body"

    return zones


def compute_semantic_zones(repo, document_id: str) -> None:
    hypotheses = repo.fetch_zone_hypotheses(document_id)

    if not hypotheses:
        return

    # ---------------------------------------------------------
    # STEP 1: normalize format
    # ---------------------------------------------------------

    zones = [
        {
            "zone_type": z["zone_type"],
            "start_block_index": z["start_block_index"],
            "end_block_index": z["end_block_index"],
            "confidence": z.get("confidence", 0.7),
        }
        for z in hypotheses
    ]

    # ---------------------------------------------------------
    # STEP 2: merge same neighbors
    # ---------------------------------------------------------

    zones = _merge_adjacent(zones)

    # ---------------------------------------------------------
    # STEP 3: remove small islands
    # ---------------------------------------------------------

    zones = _absorb_small_zones(zones)

    # ---------------------------------------------------------
    # STEP 4: enforce semantic defaults
    # ---------------------------------------------------------

    zones = _enforce_body_default(zones)

    # ---------------------------------------------------------
    # STEP 5: merge again (after relabeling)
    # ---------------------------------------------------------

    zones = _merge_adjacent(zones)

    # ---------------------------------------------------------
    # STORE
    # ---------------------------------------------------------

    repo.store_zones(document_id, zones)
