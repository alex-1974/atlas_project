from __future__ import annotations

from collections import defaultdict


def _fetch_blocks(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select block_id, page_index, block_index, x0, y0, x1, y1, text
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_spans(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                page_index,
                x0, y0, x1, y1,
                text,
                font_name,
                font_size,
                font_flags,
                is_bold,
                is_italic
            from du_layout_spans
            where document_id = %s
            order by page_index, reading_order
            """,
            (document_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _intersects(block: dict, span: dict, tol: float = 1.0) -> bool:
    if int(block["page_index"]) != int(span["page_index"]):
        return False
    if None in (
        block["x0"], block["y0"], block["x1"], block["y1"],
        span["x0"], span["y0"], span["x1"], span["y1"],
    ):
        return False

    return not (
        float(span["x1"]) < float(block["x0"]) - tol
        or float(span["x0"]) > float(block["x1"]) + tol
        or float(span["y1"]) < float(block["y0"]) - tol
        or float(span["y0"]) > float(block["y1"]) + tol
    )


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def compute_typography(repo, document_id: str) -> None:
    blocks = _fetch_blocks(repo, document_id)
    spans = _fetch_spans(repo, document_id)
    if not blocks:
        return

    spans_by_page: dict[int, list[dict]] = defaultdict(list)
    for span in spans:
        spans_by_page[int(span["page_index"])].append(span)

    page_font_sizes: dict[int, list[float]] = defaultdict(list)
    for span in spans:
        if span["font_size"] is not None:
            page_font_sizes[int(span["page_index"])].append(float(span["font_size"]))

    page_max_font = {
        page_index: (max(values) if values else None)
        for page_index, values in page_font_sizes.items()
    }

    rows: list[tuple] = []

    prev_font_size = None
    prev_font_name = None

    temp_rows: list[dict] = []

    for i, block in enumerate(blocks):
        page_spans = spans_by_page.get(int(block["page_index"]), [])
        covered = [s for s in page_spans if _intersects(block, s)]

        if covered:
            dominant = max(covered, key=lambda s: len((s["text"] or "").strip()))
            font_name = dominant.get("font_name")
            font_size = float(dominant["font_size"]) if dominant.get("font_size") is not None else None
            font_flags = dominant.get("font_flags")
            bold = any(bool(s.get("is_bold")) for s in covered)
            italic = any(bool(s.get("is_italic")) for s in covered)

            total_chars = sum(len((s.get("text") or "").strip()) for s in covered)
            dominant_chars = len((dominant.get("text") or "").strip())
            dominant_font_share = (dominant_chars / total_chars) if total_chars > 0 else None
        else:
            font_name = None
            font_size = None
            font_flags = None
            bold = False
            italic = False
            dominant_font_share = None

        text = block.get("text") or ""
        all_caps = text.isupper() if text else False
        small_caps = (_caps_ratio(text) > 0.55 and not all_caps and font_size is not None)

        page_max = page_max_font.get(int(block["page_index"]))
        largest_on_page = bool(font_size is not None and page_max is not None and font_size >= page_max - 0.01)

        temp_rows.append(
            {
                "block_id": block["block_id"],
                "font_name": font_name,
                "font_family": font_name.split(",")[0] if isinstance(font_name, str) and font_name else font_name,
                "font_family_normalized": font_name.split("+")[-1].split(",")[0] if isinstance(font_name, str) and font_name else font_name,
                "font_size": font_size,
                "font_flags": font_flags,
                "bold": bold,
                "italic": italic,
                "small_caps": small_caps,
                "all_caps": all_caps,
                "largest_on_page": largest_on_page,
                "dominant_font_share": dominant_font_share,
            }
        )

    valid_sizes = [r["font_size"] for r in temp_rows if r["font_size"] is not None]
    doc_mode = None
    if valid_sizes:
        ordered = sorted(valid_sizes)
        doc_mode = ordered[len(ordered) // 2]

    for i, row in enumerate(temp_rows):
        prev_row = temp_rows[i - 1] if i > 0 else None
        next_row = temp_rows[i + 1] if i + 1 < len(temp_rows) else None

        font_size = row["font_size"]
        prev_font_size = prev_row["font_size"] if prev_row else None
        next_font_size = next_row["font_size"] if next_row else None

        font_ratio = (float(font_size) / float(doc_mode)) if font_size is not None and doc_mode not in (None, 0) else None
        font_size_delta_prev = (float(font_size) - float(prev_font_size)) if font_size is not None and prev_font_size is not None else None
        font_size_delta_next = (float(font_size) - float(next_font_size)) if font_size is not None and next_font_size is not None else None

        rows.append(
            (
                row["block_id"],
                row["font_name"],
                row["font_family"],
                row["font_size"],
                font_ratio,
                row["bold"],
                row["italic"],
                row["small_caps"],
                row["all_caps"],
                row["largest_on_page"],
                bool(font_size_delta_prev is not None and font_size_delta_prev > 0.1),
                bool(font_size_delta_next is not None and font_size_delta_next > 0.1),
                bool(prev_row is not None and row["font_name"] != prev_row["font_name"]),
                bool(next_row is not None and row["font_name"] != next_row["font_name"]),
                bool(font_size_delta_prev is not None and abs(font_size_delta_prev) > 0.1),
                bool(font_size_delta_next is not None and abs(font_size_delta_next) > 0.1),
                bool(font_size is not None and doc_mode is not None and abs(float(font_size) - float(doc_mode)) < 0.1),
                row["font_family_normalized"],
                row["dominant_font_share"],
                font_size_delta_prev,
                font_size_delta_next,
            )
        )

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_typography (
                block_id,
                font_name,
                font_family,
                font_size,
                font_ratio,
                bold,
                italic,
                small_caps,
                all_caps,
                largest_on_page,
                larger_than_prev,
                larger_than_next,
                font_name_change_prev,
                font_name_change_next,
                font_size_change_prev,
                font_size_change_next,
                is_document_font_mode,
                font_family_normalized,
                dominant_font_share,
                font_size_delta_prev,
                font_size_delta_next
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (block_id) do update set
                font_name = excluded.font_name,
                font_family = excluded.font_family,
                font_size = excluded.font_size,
                font_ratio = excluded.font_ratio,
                bold = excluded.bold,
                italic = excluded.italic,
                small_caps = excluded.small_caps,
                all_caps = excluded.all_caps,
                largest_on_page = excluded.largest_on_page,
                larger_than_prev = excluded.larger_than_prev,
                larger_than_next = excluded.larger_than_next,
                font_name_change_prev = excluded.font_name_change_prev,
                font_name_change_next = excluded.font_name_change_next,
                font_size_change_prev = excluded.font_size_change_prev,
                font_size_change_next = excluded.font_size_change_next,
                is_document_font_mode = excluded.is_document_font_mode,
                font_family_normalized = excluded.font_family_normalized,
                dominant_font_share = excluded.dominant_font_share,
                font_size_delta_prev = excluded.font_size_delta_prev,
                font_size_delta_next = excluded.font_size_delta_next
            """,
            rows,
        )
    repo.conn.commit()
