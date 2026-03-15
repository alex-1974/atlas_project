from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


EARLY_BLOCK_LIMIT = 40
MAP_CLUSTER_WINDOW = 12
MAP_CLUSTER_THRESHOLD = 4

BODY_START_THRESHOLD = 0.35
BODY_CONTINUE_THRESHOLD = 0.15
BODY_GAP_TOLERANCE = 1
BODY_MIN_RUN_LENGTH = 2

ZONE_SOURCE = "zone_hypotheses_v5"


def compute_zone_hypotheses(repo: DURepository, document_id: str) -> None:
    blocks = fetch_block_map(repo, document_id)

    if not blocks:
        return

    block_index_map = {b["block_index"]: b for b in blocks}
    rows = []

    header_span = detect_header_candidate(blocks)
    if header_span is not None:
        rows.append(
            build_row(document_id, "header_candidate", header_span, block_index_map)
        )

    toc_span = detect_toc_candidate(blocks)
    if toc_span is not None:
        rows.append(
            build_row(document_id, "toc_candidate", toc_span, block_index_map)
        )

    abstract_span = detect_abstract_candidate(blocks, header_span)
    if abstract_span is not None:
        rows.append(
            build_row(document_id, "abstract_candidate", abstract_span, block_index_map)
        )

    keywords_span = detect_keywords_candidate(blocks)
    if keywords_span is not None:
        rows.append(
            build_row(document_id, "keywords_candidate", keywords_span, block_index_map)
        )

    appendix_span = detect_appendix_candidate(blocks)
    if appendix_span is not None:
        rows.append(
            build_row(document_id, "appendix_candidate", appendix_span, block_index_map)
        )

    figure_caption_spans = detect_figure_caption_candidates(blocks)
    for span in figure_caption_spans:
        rows.append(
            build_row(
                document_id,
                "figure_caption_candidate",
                span,
                block_index_map,
            )
        )

    table_caption_spans = detect_table_caption_candidates(blocks)
    for span in table_caption_spans:
        rows.append(
            build_row(
                document_id,
                "table_caption_candidate",
                span,
                block_index_map,
            )
        )

    ref_spans = detect_references_candidates(blocks)
    for span in ref_spans:
        rows.append(
            build_row(document_id, "references_candidate", span, block_index_map)
        )

    body_spans = detect_body_candidates(
        blocks=blocks,
        header_span=header_span,
        toc_span=toc_span,
        abstract_span=abstract_span,
        keywords_span=keywords_span,
        ref_spans=ref_spans,
        appendix_span=appendix_span,
        figure_caption_spans=figure_caption_spans,
        table_caption_spans=table_caption_spans,
    )
    for span in body_spans:
        rows.append(
            build_row(document_id, "body_candidate", span, block_index_map)
        )

    insert_zone_hypotheses(repo, document_id, rows)


def build_row(
    document_id: str,
    zone_type: str,
    span: tuple[int, int, float],
    block_index_map: dict[int, dict],
) -> dict:
    start_idx, end_idx, score = span
    start_block = block_index_map[start_idx]
    end_block = block_index_map[end_idx]

    return {
        "document_id": document_id,
        "zone_type": zone_type,
        "start_block_index": start_idx,
        "end_block_index": end_idx,
        "page_start": start_block["page_index"],
        "page_end": end_block["page_index"],
        "score": score,
        "source": ZONE_SOURCE,
    }


def fetch_block_map(repo: DURepository, document_id: str):
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.block_index,
                b.page_index,
                b.text,

                coalesce(s.title_like, 0.0) as title_like,
                coalesce(s.author_like, 0.0) as author_like,
                coalesce(s.affiliation_like, 0.0) as affiliation_like,
                coalesce(s.date_like, 0.0) as date_like,
                coalesce(s.running_text_like, 0.0) as running_text_like,
                coalesce(s.heading_like, 0.0) as heading_like,
                coalesce(s.list_like, 0.0) as list_like,
                coalesce(s.toc_like, 0.0) as toc_like,
                coalesce(s.reference_like, 0.0) as reference_like,
                coalesce(s.bibliographic_entry_like, 0.0) as bibliographic_entry_like,
                coalesce(s.caption_like, 0.0) as caption_like,
                coalesce(s.marker_like, 0.0) as marker_like,
                coalesce(s.parenthetical_citation_like, 0.0) as parenthetical_citation_like,
                coalesce(s.journal_meta_like, 0.0) as journal_meta_like,
                coalesce(s.artifact_like, 0.0) as artifact_like,
                coalesce(s.map_label_like, 0.0) as map_label_like,
                coalesce(s.noise_like, 0.0) as noise_like,

                coalesce(g.whitespace_before, 0.0) as whitespace_before,
                coalesce(g.whitespace_after, 0.0) as whitespace_after,
                coalesce(g.centeredness, 0.0) as centeredness,
                coalesce(g.near_page_top, 0.0) as near_page_top,
                coalesce(g.near_page_bottom, 0.0) as near_page_bottom,

                coalesce(t.is_first_on_page, false) as is_first_on_page,
                coalesce(t.is_last_on_page, false) as is_last_on_page,
                coalesce(t.early_block_rank, b.block_index) as early_block_rank
            from du_blocks b
            left join du_block_signals s on s.block_id = b.block_id
            left join du_block_geometry g on g.block_id = b.block_id
            left join du_block_topology t on t.block_id = b.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def insert_zone_hypotheses(repo: DURepository, document_id: str, rows) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            delete from du_zone_hypotheses
            where document_id = %s
              and source = %s
            """,
            (document_id, ZONE_SOURCE),
        )

        if not rows:
            return

        cur.executemany(
            """
            insert into du_zone_hypotheses (
                document_id,
                zone_type,
                start_block_index,
                end_block_index,
                page_start,
                page_end,
                score,
                source
            )
            values (
                %(document_id)s,
                %(zone_type)s,
                %(start_block_index)s,
                %(end_block_index)s,
                %(page_start)s,
                %(page_end)s,
                %(score)s,
                %(source)s
            )
            """,
            rows,
        )


def detect_map_label_clusters(blocks):
    flagged = set()

    for i in range(len(blocks)):
        window = blocks[i : i + MAP_CLUSTER_WINDOW]
        if not window:
            continue

        map_count = sum(1 for b in window if b["map_label_like"] > 0.6)

        if map_count >= MAP_CLUSTER_THRESHOLD:
            for b in window:
                if b["map_label_like"] > 0.5:
                    flagged.add(b["block_index"])

    return flagged


def detect_header_candidate(blocks):
    early = blocks[:EARLY_BLOCK_LIMIT]
    if not early:
        return None

    start_idx = None
    end_idx = None
    total_score = 0.0
    count = 0

    for b in early:
        positive = (
            b["title_like"]
            + b["author_like"]
            + b["affiliation_like"]
            + b["date_like"]
            + b["journal_meta_like"]
            + 0.5 * b["centeredness"]
            + 0.5 * b["near_page_top"]
        )

        negative = (
            1.2 * b["running_text_like"]
            + 1.2 * b["toc_like"]
            + 1.0 * b["reference_like"]
            + 1.0 * b["caption_like"]
            + 1.2 * b["artifact_like"]
            + 1.5 * b["map_label_like"]
            + 1.0 * b["noise_like"]
        )

        score = positive - negative

        if start_idx is None and score > 0.25:
            start_idx = b["block_index"]

        if start_idx is not None:
            if score > 0.10:
                end_idx = b["block_index"]
                total_score += score
                count += 1
            elif b["running_text_like"] > 0.6 or b["toc_like"] > 0.6:
                break

    if start_idx is None or end_idx is None:
        return None

    return (start_idx, end_idx, total_score / max(count, 1))


def detect_toc_candidate(blocks):
    best = None

    for i, b in enumerate(blocks[:EARLY_BLOCK_LIMIT]):
        score = b["toc_like"] + 0.6 * b["list_like"] + 0.3 * b["heading_like"]

        if score < 0.7:
            continue

        start = b["block_index"]
        end = start
        total = score
        count = 1

        for j in range(i + 1, min(i + 12, len(blocks))):
            nb = blocks[j]
            nscore = nb["toc_like"] + 0.6 * nb["list_like"]

            if nscore > 0.5:
                end = nb["block_index"]
                total += nscore
                count += 1
            else:
                break

        candidate = (start, end, total / count)

        if best is None or candidate[2] > best[2]:
            best = candidate

    return best


def detect_abstract_candidate(blocks, header_span):
    if header_span is None:
        return None

    start_limit = header_span[1] + 1
    early = [b for b in blocks if b["block_index"] >= start_limit][:30]

    if not early:
        return None

    current = []
    runs = []

    for b in early:
        score = (
            1.3 * b["running_text_like"]
            - 0.8 * b["toc_like"]
            - 0.8 * b["reference_like"]
            - 0.8 * b["artifact_like"]
        )

        if score > 0.3:
            current.append((b["block_index"], score))
        else:
            if len(current) >= 2:
                runs.append(collapse_run(current))
            current = []

    if current:
        runs.append(collapse_run(current))

    if not runs:
        return None

    return max(runs, key=lambda x: x[2])


def detect_keywords_candidate(blocks):
    for b in blocks[:60]:
        text = (b["text"] or "").lower().strip()

        if (
            text.startswith("keywords")
            or text.startswith("key words")
            or text.startswith("schlagwörter")
            or text.startswith("schlüsselwörter")
        ):
            start = b["block_index"]
            return (start, start, 0.9)

    return None


def detect_appendix_candidate(blocks):
    late = blocks[int(len(blocks) * 0.6) :]

    for b in late:
        text = (b["text"] or "").lower().strip()

        if (
            text.startswith("appendix")
            or text.startswith("appendices")
            or text.startswith("anhang")
        ):
            start = b["block_index"]
            return (start, start, 0.9)

    return None


def detect_figure_caption_candidates(blocks):
    spans = []

    for b in blocks:
        text = (b["text"] or "").lower().strip()

        explicit = (
            text.startswith("fig.")
            or text.startswith("figure")
            or text.startswith("abb.")
            or text.startswith("abbildung")
        )

        if explicit or b["caption_like"] > 0.75:
            spans.append((b["block_index"], b["block_index"], max(0.85, b["caption_like"])))

    return spans


def detect_table_caption_candidates(blocks):
    spans = []

    for b in blocks:
        text = (b["text"] or "").lower().strip()

        explicit = (
            text.startswith("table")
            or text.startswith("tab.")
            or text.startswith("tabelle")
        )

        if explicit:
            spans.append((b["block_index"], b["block_index"], 0.85))

    return spans


def detect_references_candidates(blocks):
    runs = []
    current = []

    for b in blocks:
        score = (
            b["reference_like"]
            + b["bibliographic_entry_like"]
            + 0.4 * b["parenthetical_citation_like"]
        )

        if score >= 0.8:
            current.append((b["block_index"], score))
        else:
            if len(current) >= 1:
                runs.append(collapse_run(current))
            current = []

    if current:
        runs.append(collapse_run(current))

    return runs


def collapse_run(run):
    start = run[0][0]
    end = run[-1][0]
    score = sum(x[1] for x in run) / len(run)
    return (start, end, score)


def compute_body_block_score(b, map_cluster_blocks: set[int]) -> float:
    cluster_penalty = 1.5 if b["block_index"] in map_cluster_blocks else 0.0

    return (
        1.4 * b["running_text_like"]
        + 0.3 * b["heading_like"]
        - 0.7 * b["toc_like"]
        - 0.8 * b["reference_like"]
        - 0.8 * b["artifact_like"]
        - 1.2 * b["map_label_like"]
        - 0.6 * b["caption_like"]
        - cluster_penalty
    )


def detect_body_candidates(
    blocks,
    header_span,
    toc_span,
    abstract_span,
    keywords_span,
    ref_spans,
    appendix_span,
    figure_caption_spans,
    table_caption_spans,
):
    if not blocks:
        return []

    map_cluster_blocks = detect_map_label_clusters(blocks)

    excluded = set()

    if header_span is not None:
        excluded.update(range(header_span[0], header_span[1] + 1))

    if toc_span is not None:
        excluded.update(range(toc_span[0], toc_span[1] + 1))

    if abstract_span is not None:
        excluded.update(range(abstract_span[0], abstract_span[1] + 1))

    if keywords_span is not None:
        excluded.update(range(keywords_span[0], keywords_span[1] + 1))

    if appendix_span is not None:
        excluded.update(range(appendix_span[0], appendix_span[1] + 1))

    for start, end, _score in ref_spans:
        excluded.update(range(start, end + 1))

    for start, end, _score in figure_caption_spans:
        excluded.update(range(start, end + 1))

    for start, end, _score in table_caption_spans:
        excluded.update(range(start, end + 1))

    min_allowed = 0

    if header_span is not None:
        min_allowed = max(min_allowed, header_span[1] + 1)

    if toc_span is not None:
        min_allowed = max(min_allowed, toc_span[1] + 1)

    if abstract_span is not None:
        min_allowed = max(min_allowed, abstract_span[1] + 1)

    if keywords_span is not None:
        min_allowed = max(min_allowed, keywords_span[1] + 1)

    candidates = []
    current_run = []
    gap_count = 0

    for b in blocks:
        idx = b["block_index"]

        if idx < min_allowed:
            continue

        if idx in excluded:
            if len(current_run) >= BODY_MIN_RUN_LENGTH:
                trimmed = trim_run_tail(current_run)
                if len(trimmed) >= BODY_MIN_RUN_LENGTH:
                    candidates.append(collapse_run(trimmed))
            current_run = []
            gap_count = 0
            continue

        score = compute_body_block_score(b, map_cluster_blocks)

        if not current_run:
            if score >= BODY_START_THRESHOLD:
                current_run = [(idx, score)]
                gap_count = 0
            continue

        if score >= BODY_CONTINUE_THRESHOLD:
            current_run.append((idx, score))
            gap_count = 0
            continue

        gap_count += 1

        if gap_count <= BODY_GAP_TOLERANCE:
            current_run.append((idx, max(score, 0.0)))
            continue

        trimmed = trim_run_tail(current_run)

        if len(trimmed) >= BODY_MIN_RUN_LENGTH:
            candidates.append(collapse_run(trimmed))

        current_run = []
        gap_count = 0

        if score >= BODY_START_THRESHOLD:
            current_run = [(idx, score)]

    if current_run:
        trimmed = trim_run_tail(current_run)
        if len(trimmed) >= BODY_MIN_RUN_LENGTH:
            candidates.append(collapse_run(trimmed))

    return candidates


def trim_run_tail(run):
    trimmed = list(run)

    while trimmed and trimmed[-1][1] <= 0.0:
        trimmed.pop()

    return trimmed
