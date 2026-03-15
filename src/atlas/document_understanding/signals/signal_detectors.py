from __future__ import annotations

import re

from atlas.document_understanding.persistence.repository import DURepository


NUMBER_RE = re.compile(r"^\d+(\.\d+)*")
BULLET_RE = re.compile(r"^[•\-–*]")


def compute_signals(repo: DURepository, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)

    if not blocks:
        return

    rows = []

    for b in blocks:
        text = (b["text"] or "").strip()

        if not text:
            continue

        word_count = len(text.split())
        short_line = word_count <= 12
        all_caps = text.isupper()
        ends_period = text.endswith(".")
        starts_number = bool(NUMBER_RE.match(text))
        bullet = bool(BULLET_RE.match(text))

        heading_like = float(
            short_line
            and not ends_period
            and (all_caps or word_count < 12)
        )

        running_text_like = float(
            word_count >= 20
            and ends_period
        )

        reference_like = float(
            starts_number
            and word_count > 8
            and ends_period
        )

        toc_like = float(
            starts_number
            and short_line
            and not ends_period
        )

        list_like = float(
            bullet or (starts_number and word_count < 10)
        )

        rows.append(
            {
                "block_id": b["block_id"],
                "heading_like": heading_like,
                "running_text_like": running_text_like,
                "reference_like": reference_like,
                "toc_like": toc_like,
                "list_like": list_like,
            }
        )

    insert_block_signals(repo, rows)


def insert_block_signals(repo: DURepository, rows) -> None:
    rows = list(rows)
    if not rows:
        return

    with repo.conn.cursor() as cur:
        cur.executemany(
            """
            insert into du_block_signals (
                block_id,
                heading_like,
                running_text_like,
                reference_like,
                toc_like,
                list_like
            )
            values (
                %(block_id)s,
                %(heading_like)s,
                %(running_text_like)s,
                %(reference_like)s,
                %(toc_like)s,
                %(list_like)s
            )
            on conflict (block_id) do update set
                heading_like = excluded.heading_like,
                running_text_like = excluded.running_text_like,
                reference_like = excluded.reference_like,
                toc_like = excluded.toc_like,
                list_like = excluded.list_like
            """,
            rows,
        )
