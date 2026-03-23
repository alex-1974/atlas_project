from __future__ import annotations

from typing import Any


# ------------------------------------------------------------
# utils
# ------------------------------------------------------------

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_bool(v: Any) -> bool:
    return bool(v)


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


# ------------------------------------------------------------
# block-level evidence
# ------------------------------------------------------------

def _front_signal(block: dict[str, Any], body_font: float) -> float:
    text = _norm(block.get("text"))
    if not text:
        return 0.0

    score = 0.0

    doc_y = _safe_float(block.get("doc_y_ratio"), 1.0)
    page_y = _safe_float(block.get("page_y_ratio"), 1.0)
    front_score = _safe_float(block.get("front_matter_score"))
    title_like = _safe_float(block.get("title_like"))
    author_like = _safe_float(block.get("author_like"))
    affiliation_like = _safe_float(block.get("affiliation_like"))
    date_like = _safe_float(block.get("date_like"))
    journal_meta_like = _safe_float(block.get("journal_meta_like"))
    centeredness = _safe_float(block.get("centeredness"))
    font_size = _safe_float(block.get("font_size"))
    heading_score = _safe_float(block.get("heading_score"))
    body_score = _safe_float(block.get("body_score"))
    reference_score = _safe_float(block.get("reference_score"))
    caption_score = _safe_float(block.get("caption_score"))
    is_figure_marker = _safe_bool(block.get("is_figure_marker"))
    is_references_marker = _safe_bool(block.get("is_references_marker"))
    running_header_like = _safe_bool(block.get("running_header_like"))
    repeated_across_pages = _safe_bool(block.get("repeated_across_pages"))

    if reference_score > 0.4 or caption_score > 0.4 or is_figure_marker or is_references_marker:
        return 0.0

    if doc_y <= 0.18:
        score += 0.35
    if page_y <= 0.22:
        score += 0.15

    score += 0.35 * min(front_score, 1.0)
    score += 0.30 * min(title_like, 1.0)
    score += 0.25 * min(author_like, 1.0)
    score += 0.20 * min(affiliation_like, 1.0)
    score += 0.15 * min(date_like, 1.0)
    score += 0.20 * min(journal_meta_like, 1.0)

    if centeredness >= 0.55:
        score += 0.15
    if font_size >= body_font + 1.0:
        score += 0.15

    if running_header_like or repeated_across_pages:
        score += 0.10

    # strong running text should weaken front
    if body_score > heading_score and len(text.split()) >= 12:
        score -= 0.25

    return max(0.0, min(1.0, score))


def _body_signal(block: dict[str, Any], body_font: float) -> float:
    text = _norm(block.get("text"))
    if not text:
        return 0.0

    score = 0.0

    body_score = _safe_float(block.get("body_score"))
    context_body_score = _safe_float(block.get("context_body_score"))
    heading_score = _safe_float(block.get("heading_score"))
    front_score = _safe_float(block.get("front_matter_score"))
    back_score = _safe_float(block.get("back_matter_score"))
    reference_score = _safe_float(block.get("reference_score"))
    caption_score = _safe_float(block.get("caption_score"))
    word_count = _safe_int(block.get("word_count"))
    sentence_count = _safe_int(block.get("sentence_count"))
    page_y = _safe_float(block.get("page_y_ratio"), 0.5)
    font_size = _safe_float(block.get("font_size"))

    score += 0.45 * min(body_score, 1.0)
    score += 0.35 * min(context_body_score, 1.0)

    if word_count >= 10:
        score += 0.15
    if sentence_count >= 1:
        score += 0.10
    if 0.10 <= page_y <= 0.90:
        score += 0.10
    if abs(font_size - body_font) <= 1.0:
        score += 0.10

    score -= 0.20 * min(front_score, 1.0)
    score -= 0.20 * min(back_score, 1.0)
    score -= 0.25 * min(reference_score, 1.0)
    score -= 0.15 * min(caption_score, 1.0)

    if heading_score > body_score and word_count <= 6:
        score += 0.05

    return max(0.0, min(1.0, score))


def _back_signal(block: dict[str, Any], total_blocks: int) -> float:
    text = _norm(block.get("text"))
    if not text:
        return 0.0

    score = 0.0

    idx = _safe_int(block.get("block_index"))
    back_score = _safe_float(block.get("back_matter_score"))
    reference_score = _safe_float(block.get("reference_score"))
    is_references_marker = _safe_bool(block.get("is_references_marker"))
    is_appendix_marker = _safe_bool(block.get("is_appendix_marker"))
    contains_citation_author_year = _safe_bool(block.get("contains_citation_author_year"))
    contains_citation_bracket = _safe_bool(block.get("contains_citation_bracket"))
    contains_year = _safe_bool(block.get("contains_year"))
    digit_density = _safe_float(block.get("digit_density"))
    punctuation_density = _safe_float(block.get("punctuation_density"))
    italic = _safe_bool(block.get("italic"))
    word_count = _safe_int(block.get("word_count"))

    frac = idx / max(total_blocks - 1, 1)

    if frac >= 0.75:
        score += 0.20
    if frac >= 0.85:
        score += 0.20

    score += 0.35 * min(back_score, 1.0)
    score += 0.35 * min(reference_score, 1.0)

    if is_references_marker:
        score += 0.50
    if is_appendix_marker:
        score += 0.50

    if any(k in text for k in ("reference", "bibliograph", "works cited", "literature", "appendix", "acknowledg")):
        score += 0.40

    if contains_citation_author_year or contains_citation_bracket:
        score += 0.15
    if contains_year and word_count >= 4:
        score += 0.10
    if digit_density >= 0.08:
        score += 0.05
    if punctuation_density >= 0.08:
        score += 0.05
    if italic and word_count >= 6:
        score += 0.05

    return max(0.0, min(1.0, score))


def _estimate_body_font(blocks: list[dict[str, Any]]) -> float:
    sizes = sorted(_safe_float(b.get("font_size")) for b in blocks if b.get("font_size") is not None)
    if not sizes:
        return 10.0
    return sizes[len(sizes) // 2]


# ------------------------------------------------------------
# boundaries
# ------------------------------------------------------------

def _detect_body_start(blocks: list[dict[str, Any]], body_font: float) -> int:
    """
    End front matter after the last clearly front-like block in the early document,
    but stop the scan once stable body evidence appears.
    """
    last_front_like = -1
    seen_body_like = False

    early_limit = max(30, int(len(blocks) * 0.25))

    for block in blocks:
        idx = _safe_int(block.get("block_index"))
        if idx > early_limit and seen_body_like:
            break

        front = _front_signal(block, body_font)
        body = _body_signal(block, body_font)

        if front >= 0.45:
            last_front_like = idx

        if body >= 0.55:
            seen_body_like = True

    return max(0, last_front_like + 1)


def _detect_back_start(blocks: list[dict[str, Any]], total_blocks: int) -> int | None:
    """
    Prefer strong late-document anchors. Do not depend on heading candidates.
    """
    threshold = int(total_blocks * 0.65)

    best_idx: int | None = None
    best_score = 0.0

    for block in blocks:
        idx = _safe_int(block.get("block_index"))
        if idx < threshold:
            continue

        score = _back_signal(block, total_blocks)

        if score > best_score and score >= 0.55:
            best_score = score
            best_idx = idx

    if best_idx is not None:
        return best_idx

    # fallback only very late
    fallback_threshold = int(total_blocks * 0.85)
    for block in blocks:
        idx = _safe_int(block.get("block_index"))
        if idx < fallback_threshold:
            continue
        if _back_signal(block, total_blocks) >= 0.40:
            return idx

    return None


# ------------------------------------------------------------
# main
# ------------------------------------------------------------

def compute_zones(repo, document_id: str) -> None:
    blocks = repo.fetch_block_records(document_id)

    if not blocks:
        repo.store_zone_hypotheses(document_id, [])
        repo.store_semantic_zones(document_id, [])
        return

    blocks = sorted(blocks, key=lambda b: _safe_int(b.get("block_index")))
    total_blocks = len(blocks)
    body_font = _estimate_body_font(blocks)

    body_start = _detect_body_start(blocks, body_font)
    back_start = _detect_back_start(blocks, total_blocks)

    if back_start is not None and back_start <= body_start:
        back_start = None

    hypotheses: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []

    if body_start > 0:
        front = {
            "zone_type": "front",
            "start_block_index": 0,
            "end_block_index": body_start - 1,
            "confidence": 0.78,
            "source": "zones.block_boundary_v3",
        }
        hypotheses.append(front)
        semantic.append(front)

    if back_start is not None:
        body = {
            "zone_type": "body",
            "start_block_index": body_start,
            "end_block_index": back_start - 1,
            "confidence": 0.86,
            "source": "zones.block_boundary_v3",
        }
    else:
        body = {
            "zone_type": "body",
            "start_block_index": body_start,
            "end_block_index": total_blocks - 1,
            "confidence": 0.68,
            "source": "zones.block_boundary_v3",
        }
    hypotheses.append(body)
    semantic.append(body)

    if back_start is not None and back_start < total_blocks:
        back = {
            "zone_type": "back",
            "start_block_index": back_start,
            "end_block_index": total_blocks - 1,
            "confidence": 0.90,
            "source": "zones.block_boundary_v3",
        }
        hypotheses.append(back)
        semantic.append(back)

    repo.store_zone_hypotheses(document_id, hypotheses)
    repo.store_semantic_zones(document_id, semantic)
