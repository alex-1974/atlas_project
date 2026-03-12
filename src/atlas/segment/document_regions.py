from __future__ import annotations

import time
import typer
from atlas.db.connection import get_connection
from atlas.segment.block_evidence import build_scored_blocks
from atlas.segment.region_assembly import assemble_regions


def _get_documents_to_segment(force: bool) -> list[tuple[str, str]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute(
                    """
                    select
                        d.document_id,
                        et.text_full
                    from documents d
                    join lateral (
                        select text_full
                        from extracted_texts
                        where document_id = d.document_id
                          and extract_status = 'ok'
                        order by created_at desc
                        limit 1
                    ) et on true
                    where et.text_full is not null
                      and btrim(et.text_full) <> ''
                    """
                )
            else:
                cur.execute(
                    """
                    select
                        d.document_id,
                        et.text_full
                    from documents d
                    join lateral (
                        select text_full
                        from extracted_texts
                        where document_id = d.document_id
                          and extract_status = 'ok'
                        order by created_at desc
                        limit 1
                    ) et on true
                    where et.text_full is not null
                      and btrim(et.text_full) <> ''
                      and not exists (
                          select 1
                          from document_regions r
                          where r.document_id = d.document_id
                      )
                    """
                )
            return cur.fetchall()

def segment_document_regions(force: bool = False) -> int:
    rows = _get_documents_to_segment(force)
    total = len(rows)
    written = 0
    started = time.time()

    typer.echo(f"segment-regions: {total} documents queued")

    with get_connection() as conn, conn.cursor() as cur:
        for idx, (document_id, text) in enumerate(rows, start=1):
            doc_started = time.time()

            blocks_started = time.time()
            blocks = build_scored_blocks(text or "")
            blocks_elapsed = time.time() - blocks_started

            assembly_started = time.time()
            regions = assemble_regions(blocks, text or "")
            assembly_elapsed = time.time() - assembly_started

            db_started = time.time()

            cur.execute(
                "delete from document_regions where document_id = %s",
                (document_id,),
            )

            for region_index, region in enumerate(regions, start=1):
                cur.execute(
                    """
                    insert into document_regions (
                        document_id,
                        region_index,
                        region_type,
                        start_char,
                        end_char,
                        text,
                        confidence
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document_id,
                        region_index,
                        region.region_type,
                        region.start_char,
                        region.end_char,
                        region.text,
                        region.confidence,
                    ),
                )

            db_elapsed = time.time() - db_started
            doc_elapsed = time.time() - doc_started

            written += 1

            if doc_elapsed > 1.0:
                typer.echo(
                    f"slow doc {document_id}: "
                    f"total={doc_elapsed:.2f}s "
                    f"blocks={blocks_elapsed:.2f}s "
                    f"assembly={assembly_elapsed:.2f}s "
                    f"db={db_elapsed:.2f}s "
                    f"blocks_n={len(blocks)} "
                    f"regions_n={len(regions)}"
                )

            if idx == 1 or idx % 25 == 0 or idx == total:
                elapsed = time.time() - started
                rate = idx / elapsed if elapsed > 0 else 0.0
                typer.echo(
                    f"[{idx}/{total}] processed, "
                    f"written={written}, "
                    f"elapsed={elapsed:.1f}s, "
                    f"rate={rate:.2f} docs/s"
                )

    return written
