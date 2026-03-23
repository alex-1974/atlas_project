from __future__ import annotations


ZONE_TITLE_PAGE = "title_page"
ZONE_ABSTRACT = "abstract"
ZONE_TOC = "toc"
ZONE_BODY = "body"
ZONE_REFERENCES = "references"
ZONE_APPENDIX = "appendix"
ZONE_FRONT_MATTER = "front_matter"
ZONE_BACK_MATTER = "back_matter"

ALL_ZONES = (
    ZONE_TITLE_PAGE,
    ZONE_ABSTRACT,
    ZONE_TOC,
    ZONE_BODY,
    ZONE_REFERENCES,
    ZONE_APPENDIX,
    ZONE_FRONT_MATTER,
    ZONE_BACK_MATTER,
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
    return " ".join(text.split()).strip().lower()


def _is_reference_heading(text: str | None) -> bool:
    value = _normalize(text)
    return value in {
        "references",
        "bibliography",
        "works cited",
        "literatur",
        "literaturverzeichnis",
        "quellen",
    }


def _is_abstract_heading(text: str | None) -> bool:
    value = _normalize(text)
    return value in {
        "abstract",
        "summary",
        "zusammenfassung",
        "résumé",
        "resume",
    }


def _is_toc_heading(text: str | None) -> bool:
    value = _normalize(text)
    return value in {
        "contents",
        "table of contents",
        "inhalt",
        "inhaltsverzeichnis",
    }


def _is_appendix_heading(text: str | None) -> bool:
    value = _normalize(text)
    return value in {
        "appendix",
        "appendices",
        "anhang",
        "beilage",
    }


def _load_blocks(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.page_index,
                b.block_index,
                b.text,
                r.role,
                c.front_matter_score,
                c.body_score,
                c.back_matter_score
            from du_blocks b
            left join du_block_roles r
                on r.block_id = b.block_id
            left join du_block_context c
                on c.block_id = b.block_id
            where b.document_id = %s
            order by b.page_index, b.block_index
            """,
            (document_id,),
        )
        rows = cur.fetchall()

    out = []
    for row in rows:
        out.append(
            {
                "block_id": row[0],
                "page_index": row[1],
                "block_index": row[2],
                "text": row[3],
                "role": row[4],
                "front_matter_score": _safe_float(row[5]),
                "body_score": _safe_float(row[6]),
                "back_matter_score": _safe_float(row[7]),
            }
        )
    return out


def _load_hypotheses_by_block_index(
    repo,
    document_id: str,
) -> dict[int, list[tuple[str, float]]]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                zone_type,
                start_block_index,
                end_block_index,
                score
            from du_zone_hypotheses
            where document_id = %s
            order by start_block_index, end_block_index
            """,
            (document_id,),
        )
        rows = cur.fetchall()

    hypotheses_by_block_index: dict[int, list[tuple[str, float]]] = {}

    for zone_type, start_idx, end_idx, score in rows:
        if start_idx is None or end_idx is None:
            continue

        start_i = int(start_idx)
        end_i = int(end_idx)
        zone_score = _safe_float(score)

        for block_index in range(start_i, end_i + 1):
            hypotheses_by_block_index.setdefault(block_index, []).append(
                (str(zone_type), zone_score)
            )

    return hypotheses_by_block_index


def _init_zone_scores() -> dict[str, float]:
    return {zone: 0.0 for zone in ALL_ZONES}


def _apply_phase_priors(block: dict, scores: dict[str, float]) -> None:
    front = _safe_float(block.get("front_matter_score"))
    body = _safe_float(block.get("body_score"))
    back = _safe_float(block.get("back_matter_score"))
    page_index = block.get("page_index")

    scores[ZONE_FRONT_MATTER] += 0.70 * front
    scores[ZONE_BODY] += 0.70 * body
    scores[ZONE_BACK_MATTER] += 0.70 * back

    if page_index is not None:
        try:
            p = int(page_index)
        except (TypeError, ValueError):
            p = None

        if p is not None:
            if p <= 1:
                scores[ZONE_FRONT_MATTER] += 0.10
                scores[ZONE_TITLE_PAGE] += 0.08
            else:
                scores[ZONE_BODY] += 0.05


def _apply_role_priors(block: dict, scores: dict[str, float]) -> None:
    role = (block.get("role") or "").strip().lower()
    text = block.get("text") or ""

    if role == "title":
        scores[ZONE_TITLE_PAGE] += 0.85
        scores[ZONE_FRONT_MATTER] += 0.45
        scores[ZONE_BODY] -= 0.20

    elif role == "author":
        scores[ZONE_TITLE_PAGE] += 0.55
        scores[ZONE_FRONT_MATTER] += 0.40
        scores[ZONE_BODY] -= 0.10

    elif role == "front_matter":
        scores[ZONE_FRONT_MATTER] += 0.70
        scores[ZONE_TITLE_PAGE] += 0.20

    elif role == "heading":
        scores[ZONE_BODY] += 0.25

        if _is_abstract_heading(text):
            scores[ZONE_ABSTRACT] += 1.10
            scores[ZONE_FRONT_MATTER] += 0.20

        if _is_reference_heading(text):
            scores[ZONE_REFERENCES] += 1.10
            scores[ZONE_BACK_MATTER] += 0.30

        if _is_toc_heading(text):
            scores[ZONE_TOC] += 1.10
            scores[ZONE_FRONT_MATTER] += 0.20

        if _is_appendix_heading(text):
            scores[ZONE_APPENDIX] += 1.10
            scores[ZONE_BACK_MATTER] += 0.30

    elif role == "reference":
        scores[ZONE_REFERENCES] += 0.95
        scores[ZONE_BACK_MATTER] += 0.40
        scores[ZONE_BODY] -= 0.20

    elif role == "caption":
        scores[ZONE_BODY] += 0.35

    elif role == "page_furniture":
        scores[ZONE_BODY] -= 0.30
        scores[ZONE_FRONT_MATTER] -= 0.10
        scores[ZONE_BACK_MATTER] -= 0.10

    elif role == "noise":
        scores[ZONE_BODY] -= 0.20

    else:
        scores[ZONE_BODY] += 0.15


def _apply_hypothesis_support(
    block_index: int,
    hypotheses_by_block_index: dict[int, list[tuple[str, float]]],
    scores: dict[str, float],
) -> None:
    for zone_type, score in hypotheses_by_block_index.get(block_index, []):
        if zone_type in scores:
            scores[zone_type] += 1.20 * _safe_float(score)


def _apply_neighbor_bias(
    prev_best_zone: str | None,
    next_best_zone: str | None,
    scores: dict[str, float],
) -> None:
    if prev_best_zone in scores:
        scores[prev_best_zone] += 0.10
    if next_best_zone in scores:
        scores[next_best_zone] += 0.05


def _best_zone(scores: dict[str, float]) -> str:
    return max(scores.items(), key=lambda item: item[1])[0]


def _normalize_positive(scores: dict[str, float]) -> dict[str, float]:
    positive = {k: max(0.0, v) for k, v in scores.items()}
    total = sum(positive.values())

    if total <= 0.0:
        return {ZONE_BODY: 1.0}

    return {
        zone: value / total
        for zone, value in positive.items()
        if value > 0.0
    }


def compute_zone_memberships(repo, document_id: str) -> None:
    blocks = _load_blocks(repo, document_id)
    hypotheses_by_block_index = _load_hypotheses_by_block_index(repo, document_id)

    if not blocks:
        return

    raw_scores_by_block_id: dict[str, dict[str, float]] = {}

    for block in blocks:
        block_id = str(block["block_id"])
        block_index = int(block["block_index"])

        scores = _init_zone_scores()

        _apply_phase_priors(block, scores)
        _apply_role_priors(block, scores)
        _apply_hypothesis_support(block_index, hypotheses_by_block_index, scores)

        raw_scores_by_block_id[block_id] = scores

    ordered_ids = [str(block["block_id"]) for block in blocks]

    best_zone_by_id: dict[str, str] = {}
    for block_id in ordered_ids:
        best_zone_by_id[block_id] = _best_zone(raw_scores_by_block_id[block_id])

    for i, block in enumerate(blocks):
        block_id = str(block["block_id"])
        scores = raw_scores_by_block_id[block_id]

        prev_best = best_zone_by_id[ordered_ids[i - 1]] if i > 0 else None
        next_best = best_zone_by_id[ordered_ids[i + 1]] if i + 1 < len(ordered_ids) else None

        _apply_neighbor_bias(prev_best, next_best, scores)

    memberships = []

    for block in blocks:
        block_id = block["block_id"]
        norm = _normalize_positive(raw_scores_by_block_id[str(block_id)])

        for zone_type, membership in norm.items():
            memberships.append(
                (
                    block_id,
                    zone_type,
                    float(membership),
                    "inference.zone_memberships.v2",
                )
            )

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            delete from du_block_zone_memberships
            where block_id in (
                select block_id
                from du_blocks
                where document_id = %s
            )
            """,
            (document_id,),
        )

        cur.executemany(
            """
            insert into du_block_zone_memberships
            (
                block_id,
                zone_type,
                membership,
                source
            )
            values (%s, %s, %s, %s)
            """,
            memberships,
        )

    repo.conn.commit()
