from __future__ import annotations

import re
from collections import Counter


HEADER_BAND_RATIO = 0.12
FOOTER_BAND_RATIO = 0.10
HEADER_WORD_MAX = 16


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _normalize_running_header(text: str) -> str:
    text = _normalize(text)
    text = re.sub(r"^\d+\s+", "", text)
    text = re.sub(r"\s+\d+$", "", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len((text or "").split())


def _caps_ratio(text: str) -> float:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _fetch_blocks(repo, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.page_index,
                b.block_index,
                b.text,
                b.page_y0,
                b.page_y1,
                p.width as page_width,
                p.height as page_height
            from du_blocks b
            left join du_pages p
              on p.document_id = b.document_id
             and p.page_index = b.page_index
            where b.document_id = %s
            order by b.page_index, b.block_index
            """,
            (document_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_topology_signals(repo, document_id: str) -> dict[str, dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                t.block_id,
                t.odd_even_page,
                t.early_on_page_score,
                t.late_on_page_score
            from du_block_topology_signals t
            where t.block_id in (
                select block_id from du_blocks where document_id = %s
            )
            """,
            (document_id,),
        )
        cols = [d[0] for d in cur.description]
        out: dict[str, dict] = {}
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            out[str(rec["block_id"])] = rec
        return out


def _band(row: dict) -> str | None:
    y0 = row.get("page_y0")
    y1 = row.get("page_y1")
    page_height = row.get("page_height")

    if y0 is None or y1 is None or page_height in (None, 0):
        return None

    y0 = float(y0)
    y1 = float(y1)
    page_height = float(page_height)

    if y1 <= page_height * HEADER_BAND_RATIO:
        return "header"
    if y0 >= page_height * (1.0 - FOOTER_BAND_RATIO):
        return "footer"
    return None


def _page_number_like(text: str) -> bool:
    value = " ".join((text or "").split()).strip()
    return bool(re.fullmatch(r"\d{1,4}", value))


def _first_page_meta_like(text: str) -> bool:
    low = _normalize(text)
    return any(
        token in low
        for token in (
            "doi:",
            "doi ",
            "copyright",
            "©",
            "vol.",
            "volume",
            "issue",
            "vernacular architecture",
            "openchoice",
            "creative commons",
        )
    )


def _running_header_text_like(text: str) -> bool:
    value = " ".join((text or "").split()).strip()
    if not value:
        return False

    if _page_number_like(value):
        return False

    wc = _word_count(value)
    if wc == 0 or wc > HEADER_WORD_MAX:
        return False

    if value[:1].isdigit():
        return True

    if _caps_ratio(value) >= 0.55:
        return True

    if value.istitle():
        return True

    return False


def _running_footer_text_like(text: str) -> bool:
    value = " ".join((text or "").split()).strip()
    if not value:
        return False

    low = value.lower()
    if "doi" in low or "copyright" in low or "creative commons" in low:
        return True

    if _page_number_like(value):
        return True

    if _word_count(value) <= 12 and _caps_ratio(value) >= 0.5:
        return True

    return False


def compute_page_furniture(repo, document_id: str) -> None:
    rows = _fetch_blocks(repo, document_id)
    if not rows:
        return

    topology_map = _fetch_topology_signals(repo, document_id)

    repeated_counts = Counter()
    parity_counts = Counter()
    normalized_records: dict[str, dict] = {}

    for row in rows:
        block_id = str(row["block_id"])
        page_index = int(row["page_index"])
        text = row.get("text") or ""
        band = _band(row)
        odd_even = topology_map.get(block_id, {}).get("odd_even_page")
        normalized_running = _normalize_running_header(text)
        normalized_plain = _normalize(text)

        normalized_records[block_id] = {
            "band": band,
            "page_index": page_index,
            "odd_even_page": odd_even,
            "normalized_running": normalized_running,
            "normalized_plain": normalized_plain,
            "text": text,
        }

        if band == "header" and normalized_running:
            repeated_counts[("header", normalized_running)] += 1
            if odd_even:
                parity_counts[("header", odd_even, normalized_running)] += 1

        if band == "footer" and normalized_plain:
            repeated_counts[("footer", normalized_plain)] += 1
            if odd_even:
                parity_counts[("footer", odd_even, normalized_plain)] += 1

    signal_rows: list[tuple] = []
    compatibility_updates: list[tuple] = []

    for row in rows:
        block_id = str(row["block_id"])
        page_index = int(row["page_index"])
        text = row.get("text") or ""
        band = _band(row)
        odd_even = topology_map.get(block_id, {}).get("odd_even_page")

        is_top_band = band == "header"
        is_bottom_band = band == "footer"

        page_number_like = _page_number_like(text)
        first_page_meta_like = bool(page_index == 0 and _first_page_meta_like(text))

        running_header_like = False
        running_footer_like = False
        repeated_across_pages = False
        repeated_same_parity = False

        rec = normalized_records[block_id]

        if is_top_band:
            norm = rec["normalized_running"]
            if norm:
                repeated_across_pages = repeated_counts[("header", norm)] >= 2
                if odd_even:
                    repeated_same_parity = parity_counts[("header", odd_even, norm)] >= 2

            running_header_like = bool(
                not first_page_meta_like
                and is_top_band
                and (
                    repeated_across_pages
                    or repeated_same_parity
                    or _running_header_text_like(text)
                )
            )

        if is_bottom_band:
            norm = rec["normalized_plain"]
            if norm:
                repeated_across_pages = repeated_across_pages or (repeated_counts[("footer", norm)] >= 2)
                if odd_even:
                    repeated_same_parity = repeated_same_parity or (parity_counts[("footer", odd_even, norm)] >= 2)

            running_footer_like = bool(
                not first_page_meta_like
                and _running_footer_text_like(text)
                and (
                    repeated_across_pages
                    or repeated_same_parity
                    or page_number_like
                )
            )

        repeated_hint = bool(
            (
                running_header_like
                or running_footer_like
                or (page_number_like and (is_top_band or is_bottom_band))
            )
            and not first_page_meta_like
        )

        signal_rows.append(
            (
                block_id,
                is_top_band,
                is_bottom_band,
                page_number_like,
                running_header_like,
                running_footer_like,
                repeated_across_pages,
                repeated_same_parity,
                first_page_meta_like,
            )
        )

        compatibility_updates.append((repeated_hint, block_id))

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            delete from du_block_page_furniture_signals
            where block_id in (
                select block_id from du_blocks where document_id = %s
            )
            """,
            (document_id,),
        )

        cur.executemany(
            """
            insert into du_block_page_furniture_signals (
                block_id,
                is_top_band,
                is_bottom_band,
                page_number_like,
                running_header_like,
                running_footer_like,
                repeated_across_pages,
                repeated_same_parity,
                first_page_meta_like
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            signal_rows,
        )

        cur.execute(
            """
            update du_block_topology
            set repeated_header_footer_hint = false,
                updated_at = now()
            where block_id in (
                select block_id from du_blocks where document_id = %s
            )
            """,
            (document_id,),
        )

        if compatibility_updates:
            cur.executemany(
                """
                update du_block_topology
                set repeated_header_footer_hint = %s,
                    updated_at = now()
                where block_id = %s
                """,
                compatibility_updates,
            )

    repo.conn.commit()
