from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev


TOP_BAND_THRESHOLD = 0.88
BOTTOM_BAND_THRESHOLD = 0.12
MAX_CANDIDATE_WORDS = 18
MIN_PAGE_COVERAGE = 0.30
MAX_SENTENCE_RATIO = 0.40
Y_CLUSTER_TOLERANCE = 0.03
MAX_WORDCOUNT_STDDEV = 6.0


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _looks_sentence_like(text: str) -> bool:
    value = " ".join((text or "").split())
    if not value:
        return False
    wc = _word_count(value)
    if wc >= 12:
        return True
    if value.endswith((".", "!", "?")) and wc >= 6:
        return True
    if "," in value and wc >= 6:
        return True
    return False


def _cluster_by_y(candidates: list[dict], tolerance: float = Y_CLUSTER_TOLERANCE) -> list[dict]:
    clusters: list[dict] = []
    for cand in candidates:
        placed = False
        for cluster in clusters:
            if abs(cluster["y_mean"] - cand["page_y_mid"]) <= tolerance:
                cluster["items"].append(cand)
                cluster["y_values"].append(cand["page_y_mid"])
                cluster["y_mean"] = mean(cluster["y_values"])
                placed = True
                break
        if not placed:
            clusters.append(
                {
                    "items": [cand],
                    "y_values": [cand["page_y_mid"]],
                    "y_mean": cand["page_y_mid"],
                }
            )
    return clusters


def compute_page_furniture(repo, document_id: str) -> None:
    """
    Mark repeated header/footer-like blocks in du_block_topology.repeated_header_footer_hint.

    The signal is based primarily on page position and cross-page repetition of a
    functional zone, not on exact text equality.
    """
    blocks = repo.fetch_blocks(document_id)
    if not blocks:
        return

    pages: dict[int, list[dict]] = defaultdict(list)
    for block in blocks:
        pages[int(block.get("page_index") or 0)].append(block)

    total_pages = len(pages)
    if total_pages <= 1:
        return

    candidates: list[dict] = []
    for block in blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue

        page_y0 = float(block.get("page_y0") or 0.0)
        page_y1 = float(block.get("page_y1") or 0.0)
        page_y_mid = (page_y0 + page_y1) / 2.0
        is_top = page_y1 >= TOP_BAND_THRESHOLD
        is_bottom = page_y0 <= BOTTOM_BAND_THRESHOLD

        if not (is_top or is_bottom):
            continue
        if _word_count(text) > MAX_CANDIDATE_WORDS:
            continue

        candidates.append(
            {
                "block_id": block.get("block_id"),
                "page_index": int(block.get("page_index") or 0),
                "page_y_mid": page_y_mid,
                "text": text,
                "norm": _normalize_text(text),
                "word_count": _word_count(text),
                "sentence_like": _looks_sentence_like(text),
                "is_top": is_top,
                "is_bottom": is_bottom,
            }
        )

    if not candidates:
        return

    top_clusters = _cluster_by_y([c for c in candidates if c["is_top"]])
    bottom_clusters = _cluster_by_y([c for c in candidates if c["is_bottom"]])
    clusters = top_clusters + bottom_clusters

    hinted_block_ids: set[str] = set()

    for cluster in clusters:
        items = cluster["items"]
        pages_seen = {item["page_index"] for item in items}
        if len(pages_seen) < 2:
            continue

        coverage = len(pages_seen) / total_pages
        if coverage < MIN_PAGE_COVERAGE:
            continue

        sentence_ratio = sum(1 for item in items if item["sentence_like"]) / len(items)
        if sentence_ratio > MAX_SENTENCE_RATIO:
            continue

        word_counts = [item["word_count"] for item in items]
        if len(word_counts) >= 2 and pstdev(word_counts) > MAX_WORDCOUNT_STDDEV:
            continue

        for item in items:
            hinted_block_ids.add(str(item["block_id"]))

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            update du_block_topology
            set repeated_header_footer_hint = false,
                updated_at = now()
            where block_id in (
                select block_id
                from du_blocks
                where document_id = %s
            )
            """,
            (document_id,),
        )

        if hinted_block_ids:
            cur.executemany(
                """
                update du_block_topology
                set repeated_header_footer_hint = true,
                    updated_at = now()
                where block_id = %s
                """,
                [(block_id,) for block_id in hinted_block_ids],
            )

    repo.conn.commit()
