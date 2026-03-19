# src/atlas/document_understanding/inference/consensus.py
from __future__ import annotations


ROLE_TITLE = "title"
ROLE_HEADING = "heading"
ROLE_BODY = "body"
ROLE_REFERENCE = "reference"
ROLE_CAPTION = "caption"
ROLE_NOISE = "noise"

ROLE_ORDER = (
    ROLE_TITLE,
    ROLE_HEADING,
    ROLE_BODY,
    ROLE_REFERENCE,
    ROLE_CAPTION,
    ROLE_NOISE,
)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip()


def _get_scores(row: dict) -> dict[str, float]:
    return {
        ROLE_TITLE: _safe_float(row.get("title_score")),
        ROLE_HEADING: _safe_float(row.get("heading_score")),
        ROLE_BODY: _safe_float(row.get("body_score")),
        ROLE_REFERENCE: _safe_float(row.get("reference_score")),
        ROLE_CAPTION: _safe_float(row.get("caption_score")),
        ROLE_NOISE: _safe_float(row.get("noise_score")),
    }


def _set_scores(row: dict, scores: dict[str, float]) -> None:
    row["title_score"] = max(0.0, scores[ROLE_TITLE])
    row["heading_score"] = max(0.0, scores[ROLE_HEADING])
    row["body_score"] = max(0.0, scores[ROLE_BODY])
    row["reference_score"] = max(0.0, scores[ROLE_REFERENCE])
    row["caption_score"] = max(0.0, scores[ROLE_CAPTION])
    row["noise_score"] = max(0.0, scores[ROLE_NOISE])


def _resolve_role(scores: dict[str, float]) -> str:
    best_role = ROLE_BODY
    best_score = float("-inf")

    for role in ROLE_ORDER:
        score = scores.get(role, 0.0)
        if score > best_score:
            best_role = role
            best_score = score

    return best_role


def _copy_role_row(row: dict) -> dict:
    return {
        "block_id": row["block_id"],
        "role": row.get("role"),
        "title_score": _safe_float(row.get("title_score")),
        "heading_score": _safe_float(row.get("heading_score")),
        "body_score": _safe_float(row.get("body_score")),
        "reference_score": _safe_float(row.get("reference_score")),
        "caption_score": _safe_float(row.get("caption_score")),
        "noise_score": _safe_float(row.get("noise_score")),
    }


def _is_reference_heading_text(text: str) -> bool:
    value = _normalize(text).lower()
    return value in {
        "references",
        "bibliography",
        "works cited",
        "literature",
        "literatur",
        "literaturverzeichnis",
        "quellen",
    }


def _looks_referenceish_text(text: str) -> bool:
    low = _normalize(text).lower()
    if not low:
        return False

    markers = (
        "doi",
        "vol.",
        "volume",
        "issue",
        "pp.",
        "isbn",
        "issn",
        "publisher",
        "editors",
    )
    return any(marker in low for marker in markers)


def _looks_captionish_text(text: str) -> bool:
    low = _normalize(text).lower()
    if not low:
        return False

    return (
        low.startswith("fig ")
        or low.startswith("fig. ")
        or low.startswith("figure ")
        or low.startswith("table ")
        or low.startswith("tab. ")
        or low.startswith("abb. ")
        or low.startswith("abbildung ")
        or low.startswith("tabelle ")
    )


def _count_title_like_prefix(blocks: list[dict], role_map: dict[str, dict]) -> int:
    count = 0
    for block in blocks:
        block_id = str(block["block_id"])
        row = role_map.get(block_id)
        if not row:
            continue
        if row.get("role") == ROLE_TITLE:
            count += 1
        else:
            break
    return count


def _apply_title_prefix_rule(blocks: list[dict], role_map: dict[str, dict]) -> None:
    title_prefix = _count_title_like_prefix(blocks, role_map)
    if title_prefix <= 1:
        return

    for block in blocks[1:title_prefix]:
        block_id = str(block["block_id"])
        row = role_map.get(block_id)
        if not row:
            continue

        scores = _get_scores(row)
        scores[ROLE_TITLE] *= 0.65
        scores[ROLE_HEADING] *= 0.90
        scores[ROLE_BODY] += 0.05

        _set_scores(row, scores)
        row["role"] = _resolve_role(scores)


def _apply_local_context_rules(blocks: list[dict], role_map: dict[str, dict]) -> None:
    total = len(blocks)

    for idx, block in enumerate(blocks):
        block_id = str(block["block_id"])
        row = role_map.get(block_id)
        if not row:
            continue

        text = _normalize(block.get("text"))
        scores = _get_scores(row)
        current_role = row.get("role")

        if scores[ROLE_NOISE] >= 0.80:
            scores[ROLE_TITLE] *= 0.20
            scores[ROLE_HEADING] *= 0.20
            scores[ROLE_BODY] *= 0.20
            scores[ROLE_REFERENCE] *= 0.30
            scores[ROLE_CAPTION] *= 0.30

        if _looks_captionish_text(text):
            scores[ROLE_CAPTION] += 0.25
            scores[ROLE_BODY] *= 0.85

        if _is_reference_heading_text(text):
            scores[ROLE_REFERENCE] += 0.35
            scores[ROLE_HEADING] += 0.10

        if _looks_referenceish_text(text):
            if idx < int(total * 0.50):
                scores[ROLE_REFERENCE] *= 0.55
            else:
                scores[ROLE_REFERENCE] += 0.10

        if current_role == ROLE_TITLE:
            if idx + 1 < total:
                next_id = str(blocks[idx + 1]["block_id"])
                next_row = role_map.get(next_id)
                if next_row:
                    next_scores = _get_scores(next_row)
                    next_scores[ROLE_HEADING] *= 0.85
                    next_scores[ROLE_BODY] *= 0.92
                    _set_scores(next_row, next_scores)
                    next_row["role"] = _resolve_role(next_scores)

        _set_scores(row, scores)
        row["role"] = _resolve_role(scores)


def _apply_reference_tail_rule(blocks: list[dict], role_map: dict[str, dict]) -> None:
    first_reference_idx: int | None = None

    for idx, block in enumerate(blocks):
        block_id = str(block["block_id"])
        row = role_map.get(block_id)
        text = _normalize(block.get("text"))

        if not row:
            continue

        if row.get("role") == ROLE_REFERENCE or _is_reference_heading_text(text):
            first_reference_idx = idx
            break

    if first_reference_idx is None:
        return

    threshold = int(len(blocks) * 0.50)
    if first_reference_idx < threshold:
        return

    for idx in range(first_reference_idx, len(blocks)):
        block_id = str(blocks[idx]["block_id"])
        row = role_map.get(block_id)
        if not row:
            continue

        text = _normalize(blocks[idx].get("text"))
        scores = _get_scores(row)

        if _is_reference_heading_text(text):
            scores[ROLE_REFERENCE] += 0.40
        elif _looks_referenceish_text(text):
            scores[ROLE_REFERENCE] += 0.20
        else:
            scores[ROLE_BODY] += 0.05

        _set_scores(row, scores)
        row["role"] = _resolve_role(scores)


def _materialize_rows(blocks: list[dict], role_map: dict[str, dict]) -> list[dict]:
    out: list[dict] = []

    for block in blocks:
        block_id = str(block["block_id"])
        row = role_map.get(block_id)
        if not row:
            continue

        scores = _get_scores(row)
        out.append(
            {
                "block_id": block_id,
                "role": _resolve_role(scores),
                "title_score": scores[ROLE_TITLE],
                "heading_score": scores[ROLE_HEADING],
                "body_score": scores[ROLE_BODY],
                "reference_score": scores[ROLE_REFERENCE],
                "caption_score": scores[ROLE_CAPTION],
                "noise_score": scores[ROLE_NOISE],
            }
        )

    return out


def compute_consensus(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    role_rows = repo.fetch_block_roles(document_id)

    role_map: dict[str, dict] = {
        str(row["block_id"]): _copy_role_row(row)
        for row in role_rows
    }

    if not blocks or not role_map:
        return

    _apply_title_prefix_rule(blocks, role_map)

    for _ in range(2):
        _apply_local_context_rules(blocks, role_map)
        _apply_reference_tail_rule(blocks, role_map)

    updated_rows = _materialize_rows(blocks, role_map)
    repo.store_block_roles(document_id, updated_rows)
