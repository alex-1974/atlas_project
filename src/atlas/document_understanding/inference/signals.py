# src/atlas/document_understanding/inference/signals.py
from __future__ import annotations


def _text_len(text: str | None) -> int:
    if not text:
        return 0
    return len(text.strip())


def _is_all_caps(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip()
    return t.isupper() and len(t) > 4


def _has_terminal_period(text: str | None) -> bool:
    if not text:
        return False
    return text.strip().endswith(".")


def _safe_bool(value) -> bool:
    return bool(value) if value is not None else False


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_clusters(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                page_index,
                start_block_index,
                end_block_index,
                cluster_kind,
                block_count
            from du_layout_clusters
            where document_id = %s
            """,
            (document_id,),
        )

        rows = cur.fetchall()

    clusters = []

    for row in rows:
        clusters.append(
            {
                "page_index": row[0],
                "start_block_index": row[1],
                "end_block_index": row[2],
                "cluster_kind": row[3],
                "block_count": row[4],
            }
        )

    return clusters


def _cluster_for_block(
    page_index: int | None,
    block_index: int | None,
    clusters: list[dict],
) -> dict | None:
    if page_index is None or block_index is None:
        return None

    for cluster in clusters:
        if (
            cluster["page_index"] == page_index
            and cluster["start_block_index"] <= block_index <= cluster["end_block_index"]
        ):
            return cluster

    return None


def compute_signals(repo, document_id: str) -> None:
    """
    Aggregate DU signals from:
    - blocks
    - geometry
    - typography
    - topology
    - semantic micro features
    - layout clusters

    Writes into du_block_signals.
    """

    clusters = _load_clusters(repo, document_id)

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.page_index,
                b.block_index,
                b.text,

                g.column_hint,
                g.centeredness,

                t.bold,
                t.italic,
                t.all_caps,
                t.largest_on_page,
                t.font_ratio,

                topo.is_first_on_page,
                topo.is_last_on_page,
                topo.repeated_header_footer_hint,

                sm.is_abstract_marker,
                sm.is_keywords_marker,
                sm.is_references_marker,
                sm.is_figure_marker,
                sm.is_table_marker,
                sm.is_appendix_marker,
                sm.contains_doi,
                sm.contains_year,
                sm.contains_citation_bracket,
                sm.contains_citation_author_year,

                sf.char_count,
                sf.word_count,
                sf.sentence_count,
                sf.line_count,
                sf.mean_line_length,
                sf.line_width_ratio,
                sf.capitalization_ratio,
                sf.punctuation_density,
                sf.digit_density,
                sf.ends_with_period,
                sf.ends_with_colon,
                sf.starts_with_number,
                sf.starts_with_bullet,
                sf.contains_parentheses,
                sf.contains_brackets,
                sf.contains_url,
                sf.contains_email,
                sf.is_short_line,

                ctx.doc_y_ratio,
                ctx.page_y_ratio,
                ctx.front_matter_score,
                ctx.body_score,
                ctx.back_matter_score

            from du_blocks b

            left join du_block_geometry g
                on g.block_id = b.block_id

            left join du_block_typography t
                on t.block_id = b.block_id

            left join du_block_topology topo
                on topo.block_id = b.block_id

            left join du_block_semantic_micro sm
                on sm.block_id = b.block_id

            left join du_block_surface_features sf
                on sf.block_id = b.block_id

            left join du_block_context ctx
                on ctx.block_id = b.block_id

            where b.document_id = %s
            order by b.page_index, b.block_index
            """,
            (document_id,),
        )

        rows = cur.fetchall()

    signal_rows = []

    for row in rows:
        (
            block_id,
            page_index,
            block_index,
            text,
            column_hint,
            centeredness,
            bold,
            italic,
            all_caps_typography,
            largest_on_page,
            font_ratio,
            is_first_on_page,
            is_last_on_page,
            repeated_header_footer_hint,
            is_abstract_marker,
            is_keywords_marker,
            is_references_marker,
            is_figure_marker,
            is_table_marker,
            is_appendix_marker,
            contains_doi,
            contains_year,
            contains_citation_bracket,
            contains_citation_author_year,
            char_count,
            word_count,
            sentence_count,
            line_count,
            mean_line_length,
            line_width_ratio,
            capitalization_ratio,
            punctuation_density,
            digit_density,
            ends_with_period,
            ends_with_colon,
            starts_with_number,
            starts_with_bullet,
            contains_parentheses,
            contains_brackets,
            contains_url,
            contains_email,
            is_short_line,
            doc_y_ratio,
            page_y_ratio,
            front_matter_score,
            body_score,
            back_matter_score,
        ) = row

        text_len = _text_len(text)
        all_caps = _safe_bool(all_caps_typography) or _is_all_caps(text)
        terminal_period = _safe_bool(ends_with_period) or _has_terminal_period(text)

        cluster = _cluster_for_block(page_index, block_index, clusters)

        cluster_wide = 0.0
        cluster_narrow = 0.0
        cluster_multicolumn = 0.0
        cluster_size = 0

        if cluster:
            cluster_size = int(cluster["block_count"] or 0)

            kind = cluster["cluster_kind"]
            if kind == "wide_cluster":
                cluster_wide = 1.0
            elif kind == "narrow_cluster":
                cluster_narrow = 1.0
            elif kind == "multi_column_cluster":
                cluster_multicolumn = 1.0

        title_like = 0.0
        heading_like = 0.0
        body_like = 0.0
        reference_like = 0.0
        caption_like = 0.0
        noise_like = 0.0

        # -------------------------------------------------
        # title_like
        # -------------------------------------------------

        if _safe_bool(largest_on_page):
            title_like += 0.45

        if _safe_bool(bold):
            title_like += 0.15

        if all_caps:
            title_like += 0.15

        if _safe_bool(is_first_on_page):
            title_like += 0.10

        if cluster_wide:
            title_like += 0.20

        if _safe_float(front_matter_score) > 0:
            title_like += 0.20 * _safe_float(front_matter_score)

        if _safe_float(centeredness) > 0:
            title_like += 0.20 * _safe_float(centeredness)

        if _safe_bool(is_short_line):
            title_like += 0.10

        if not terminal_period:
            title_like += 0.05

        if _safe_bool(repeated_header_footer_hint):
            title_like -= 0.40

        # -------------------------------------------------
        # heading_like
        # -------------------------------------------------

        if _safe_bool(bold):
            heading_like += 0.25

        if _safe_float(font_ratio) > 1.10:
            heading_like += 0.30

        if not terminal_period and text_len < 120:
            heading_like += 0.20

        if _safe_bool(ends_with_colon):
            heading_like += 0.10

        if _safe_bool(is_short_line):
            heading_like += 0.15

        if cluster_wide:
            heading_like += 0.10

        if _safe_float(body_score) > 0:
            heading_like += 0.10 * _safe_float(body_score)

        if _safe_bool(repeated_header_footer_hint):
            heading_like -= 0.30

        # -------------------------------------------------
        # body_like
        # -------------------------------------------------

        if text_len > 80:
            body_like += 0.35

        if terminal_period:
            body_like += 0.20

        if column_hint is not None:
            body_like += 0.15

        if cluster_multicolumn:
            body_like += 0.10

        if cluster_size >= 3:
            body_like += 0.10

        if _safe_float(body_score) > 0:
            body_like += 0.25 * _safe_float(body_score)

        if _safe_float(sentence_count) >= 2:
            body_like += 0.10

        if _safe_bool(repeated_header_footer_hint):
            body_like -= 0.35

        # -------------------------------------------------
        # reference_like
        # -------------------------------------------------

        if _safe_bool(is_references_marker):
            reference_like += 0.60

        if _safe_bool(contains_doi):
            reference_like += 0.35

        if _safe_bool(contains_citation_bracket):
            reference_like += 0.25

        if _safe_bool(contains_citation_author_year):
            reference_like += 0.25

        if _safe_bool(contains_year):
            reference_like += 0.20

        if _safe_float(back_matter_score) > 0:
            reference_like += 0.25 * _safe_float(back_matter_score)

        if _safe_float(punctuation_density) > 0.08:
            reference_like += 0.10

        if _safe_bool(contains_parentheses):
            reference_like += 0.05

        # -------------------------------------------------
        # caption_like
        # -------------------------------------------------

        if _safe_bool(is_figure_marker):
            caption_like += 0.60

        if _safe_bool(is_table_marker):
            caption_like += 0.60

        if text and text.lower().startswith(("fig", "figure", "table")):
            caption_like += 0.30

        if text_len < 200 and terminal_period:
            caption_like += 0.15

        if cluster_narrow:
            caption_like += 0.10

        if _safe_bool(is_short_line):
            caption_like += 0.10

        # -------------------------------------------------
        # noise_like
        # -------------------------------------------------

        if _safe_bool(repeated_header_footer_hint):
            noise_like += 0.70

        if _safe_bool(is_last_on_page) and text_len < 30:
            noise_like += 0.15

        if cluster_narrow:
            noise_like += 0.15

        if text_len <= 2:
            noise_like += 0.20

        if _safe_float(digit_density) > 0.5:
            noise_like += 0.10

        # clamp to non-negative
        title_like = max(0.0, title_like)
        heading_like = max(0.0, heading_like)
        body_like = max(0.0, body_like)
        reference_like = max(0.0, reference_like)
        caption_like = max(0.0, caption_like)
        noise_like = max(0.0, noise_like)

        signal_rows.append(
            (
                block_id,
                title_like,
                heading_like,
                body_like,
                reference_like,
                caption_like,
                noise_like,
            )
        )

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_signals
            (
                block_id,
                title_like,
                heading_like,
                running_text_like,
                reference_like,
                caption_like,
                noise_like
            )
            values (%s,%s,%s,%s,%s,%s,%s)
            on conflict (block_id) do update
            set
                title_like = excluded.title_like,
                heading_like = excluded.heading_like,
                running_text_like = excluded.running_text_like,
                reference_like = excluded.reference_like,
                caption_like = excluded.caption_like,
                noise_like = excluded.noise_like,
                updated_at = now()
            """,
            signal_rows,
        )

    repo.conn.commit()
