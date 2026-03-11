from __future__ import annotations

import re
import uuid

from atlas.db.connection import get_connection


PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    text = text.replace("\x00", "")
    parts = PARA_SPLIT_RE.split(text)

    paragraphs: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # sehr kurze Fragmente aussortieren
        if len(part) < 40:
            continue

        # whitespace glätten
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
                where coalesce(d.doc_state, '') in ('text_pdf', 'fallback_text_pdf')
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
                paragraphs = split_paragraphs(text_full or "")

                for i, para in enumerate(paragraphs):
                    cur.execute(
                        """
                        insert into text_segments (
                            segment_id,
                            document_id,
                            segment_index,
                            segment_type,
                            text,
                            char_length
                        )
                        values (%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            str(uuid.uuid4()),
                            document_id,
                            i,
                            "paragraph",
                            para,
                            len(para),
                        ),
                    )
                    created += 1

    return created
