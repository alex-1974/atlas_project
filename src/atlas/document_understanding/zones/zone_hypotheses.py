from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


EARLY_BLOCK_LIMIT = 40


def compute_zone_hypotheses(repo: DURepository, document_id: str) -> None:
    blocks = fetch_block_map(repo, document_id)

    if not blocks:
        return

    rows = []

    # ---------------------------------------------------------
    # Header candidate
    # ---------------------------------------------------------
    header_span = detect_header_candidate(blocks)
    if header_span is not None:
        start_idx, end_idx, score = header_span
        rows.append(
            {
                "document_id": document_id,
                "zone_type": "header_candidate",
                "start_block_index": start_idx,
                "end_block_index": end_idx,
                "page_start": blocks[start_idx]["page_index"],
                "page_end": blocks[end_idx]["page_index"],
                "score": score,
                "source": "zone_hypotheses_v1",
            }
        )

    # ---------------------------------------------------------
    # TOC candidate
    # ---------------------------------------------------------
    toc_span = detect_toc_candidate(blocks)
    if toc_span is not None:
        start_idx, end_idx, score = toc_span
        rows.append(
            {
                "document_id": document_id,
                "zone_type": "toc_candidate",
                "start_block_index": start_idx,
                "end_block_index": end_idx,
                "page_start": blocks[start_idx]["page_index"],
                "page_end": blocks[end_idx]["page_index"],
                "score": score,
                "source": "zone_hypotheses_v1",
            }
        )

    # ---------------------------------------------------------
    # References candidate
    # ---------------------------------------------------------
    ref_span = detect_references_candidate(blocks)
    if ref_span is not None:
        start_idx, end_idx, score = ref_span
        rows.append(
            {
                "document_id": document_id,
                "zone_type": "references_candidate",
                "start_block_index": start_idx,
                "end_block_index": end_idx,
                "page_start": blocks[start_idx]["page_index"],
                "page_end": blocks[end_idx]["page_index"],
                "score": score,
                "source": "zone_hypotheses_v1",
            }
        )

    # ---------------------------------------------------------
    # Body candidate
    # ---------------------------------------------------------
    body_span = detect_body_candidate(blocks, header_span, toc_span, ref_span)
    if body_span is not None:
        start_idx, end_idx, score = body_span
        rows.append(
            {
                "document_id": document_id,
                "zone_type": "body_candidate",
                "start_block_index": start_idx,
                "end_block_index": end_idx,
                "page_start": blocks[start_idx]["page_index"],
                "page_end": blocks[end_idx]["page_index"],
                "score": score,
                "source": "zone_hypotheses_v1",
            }
        )

    insert_zone_hypotheses(repo, rows)


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


def insert_zone_hypotheses(repo: DURepository, rows) -> None:
    with repo.conn.cursor() as cur:
        for r in rows:
            cur.execute(
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
                r,
            )


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
            + 1.0 * b["artifact_like"]
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


def detect_references_candidate(blocks):
    best = None

    for i, b in enumerate(blocks):
        score = b["reference_like"] + b["bibliographic_entry_like"] + 0.4 * b["parenthetical_citation_like"]

        if score < 0.8:
            continue

        start = b["block_index"]
        end = start
        total = score
        count = 1

        for j in range(i + 1, min(i + 30, len(blocks))):
            nb = blocks[j]
            nscore = nb["reference_like"] + nb["bibliographic_entry_like"]

            if nscore > 0.4:
                end = nb["block_index"]
                total += nscore
                count += 1
            else:
                break

        candidate = (start, end, total / count)

        if best is None or candidate[2] > best[2]:
            best = candidate

    return best


def detect_body_candidate(blocks, header_span, toc_span, ref_span):
    if not blocks:
        return None

    start = 0

    if header_span is not None:
        start = max(start, header_span[1] + 1)

    if toc_span is not None:
        start = max(start, toc_span[1] + 1)

    end = len(blocks) - 1

    if ref_span is not None:
        end = min(end, ref_span[0] - 1)

    if start > end:
        return None

    total = 0.0
    count = 0
    body_start = None
    body_end = None

    for i in range(start, end + 1):
        b = blocks[i]

        score = (
            1.4 * b["running_text_like"]
            + 0.3 * b["heading_like"]
            - 0.7 * b["toc_like"]
            - 0.8 * b["reference_like"]
            - 0.5 * b["artifact_like"]
        )

        if score > 0.2:
            if body_start is None:
                body_start = b["block_index"]
            body_end = b["block_index"]
            total += score
            count += 1

    if body_start is None or body_end is None:
        return None

    return (body_start, body_end, total / max(count, 1))
