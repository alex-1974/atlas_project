from __future__ import annotations

import re
import uuid

from atlas.db.connection import get_connection
from atlas.segment.page_split import split_pages

PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    text = text.replace("\x00", "")
    parts = PARA_SPLIT_RE.split(text)

    paragraphs: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if len(part) < 40:
            continue

        part = re.sub(r"[ \t]+", " ", part)
        part = re.sub(r"\n{2,}", "\n", part).strip()

        if part:
            paragraphs.append(part)

    return paragraphs


def segment_documents(force: bool = False) -> int:
    created = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute("delete from text_segments")

            cur.execute(
                """
                select
                    d.document_id,
                    e.text_full
                from documents d
                join lateral (
                    select text_full
                    from extracted_texts
                    where document_id = d.document_id
                      and extract_status = 'ok'
                    order by created_at desc
                    limit 1
                ) e on true
                where e.text_full is not null
                  and length(e.text_full) > 0
                  and (
                      %s = true
                      or not exists (
                          select 1
                          from text_segments s
                          where s.document_id = d.document_id
                      )
                  )
                """,
                (force,),
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, text_full in rows:
                pages = split_pages(text_full or "")

                global_segment_index = 0

                for page_index, _page_start, _page_end, page_text in pages:
                    paragraphs = split_paragraphs(page_text or "")

                    for para in paragraphs:
                        cur.execute(
                            """
                            insert into text_segments (
                                segment_id,
                                document_id,
                                page_index,
                                segment_index,
                                segment_type,
                                text,
                                char_length
                            )
                            values (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                str(uuid.uuid4()),
                                document_id,
                                page_index,
                                global_segment_index,
                                "paragraph",
                                para,
                                len(para),
                            ),
                        )
                        global_segment_index += 1
                        created += 1

    return created
