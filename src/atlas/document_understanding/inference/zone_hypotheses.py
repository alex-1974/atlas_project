from __future__ import annotations


ZONE_TITLE_PAGE = "title_page"
ZONE_ABSTRACT = "abstract"
ZONE_TOC = "toc"
ZONE_BODY = "body"
ZONE_REFERENCES = "references"
ZONE_APPENDIX = "appendix"
ZONE_FRONT_MATTER = "front_matter"
ZONE_BACK_MATTER = "back_matter"


def _text_lower(text: str | None) -> str:
    if not text:
        return ""
    return text.strip().lower()


def _is_abstract_heading(text: str | None) -> bool:
    return _text_lower(text).startswith("abstract")


def _is_reference_heading(text: str | None) -> bool:
    return _text_lower(text).startswith(
        ("references", "bibliography", "literature", "literatur")
    )


def _is_appendix_heading(text: str | None) -> bool:
    return _text_lower(text).startswith("appendix")


def _is_toc_heading(text: str | None) -> bool:
    return _text_lower(text).startswith(
        ("contents", "table of contents", "inhalt", "inhaltsverzeichnis")
    )


def _find_title_page_span(
    rows: list[tuple[int, int, str | None, str]]
) -> tuple[int, int] | None:
    """
    Title page = contiguous early title blocks (+ optional author).
    Hard stop after first structural break.
    """
    start = None
    end = None

    for page_index, block_index, _text, role in rows:
        if page_index != 0:
            break

        if block_index > 20:
            break

        if role == "title":
            if start is None:
                start = block_index
            end = block_index
            continue

        if role == "author" and start is not None:
            end = block_index
            continue

        if start is not None:
            break

    if start is None or end is None:
        return None

    return (start, end)


def compute_zone_hypotheses(repo, document_id: str) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.page_index,
                b.block_index,
                b.text,
                r.role
            from du_blocks b
            join du_block_roles r
                on r.block_id = b.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )
        rows = cur.fetchall()

    if not rows:
        return

    hypotheses: list[tuple[str, int, int, float]] = []
    title_span = _find_title_page_span(rows)

    current_zone = None
    start_block_index = None
    last_block_index = None

    def start_zone(zone_type: str, block_index: int) -> None:
        nonlocal current_zone, start_block_index, last_block_index
        current_zone = zone_type
        start_block_index = block_index
        last_block_index = block_index

    def extend_zone(block_index: int) -> None:
        nonlocal last_block_index
        last_block_index = block_index

    def flush() -> None:
        nonlocal current_zone, start_block_index, last_block_index
        if current_zone is None or start_block_index is None or last_block_index is None:
            return

        hypotheses.append(
            (
                current_zone,
                int(start_block_index),
                int(last_block_index),
                0.8,
            )
        )

    title_start = None
    title_end = None
    if title_span is not None:
        title_start, title_end = title_span

    for page_index, block_index, text, role in rows:
        # -----------------------------------------------------
        # HARD TITLE PAGE SPAN
        # -----------------------------------------------------
        if title_start is not None and title_end is not None:
            if block_index < title_start:
                if current_zone is None:
                    start_zone(ZONE_FRONT_MATTER, block_index)
                elif current_zone != ZONE_FRONT_MATTER:
                    flush()
                    start_zone(ZONE_FRONT_MATTER, block_index)
                else:
                    extend_zone(block_index)
                continue

            if title_start <= block_index <= title_end:
                if current_zone is None:
                    start_zone(ZONE_TITLE_PAGE, block_index)
                elif current_zone != ZONE_TITLE_PAGE:
                    flush()
                    start_zone(ZONE_TITLE_PAGE, block_index)
                else:
                    extend_zone(block_index)
                continue

            if block_index == title_end + 1:
                # after title page, default into body unless a stronger anchor appears below
                flush()
                current_zone = None
                start_block_index = None
                last_block_index = None

        # -----------------------------------------------------
        # STRONG ANCHORS
        # -----------------------------------------------------
        new_zone = None

        if role == "heading" and _is_abstract_heading(text):
            new_zone = ZONE_ABSTRACT
        elif role == "heading" and _is_toc_heading(text):
            new_zone = ZONE_TOC
        elif role == "heading" and _is_reference_heading(text):
            new_zone = ZONE_REFERENCES
        elif role == "heading" and _is_appendix_heading(text):
            new_zone = ZONE_APPENDIX
        elif role == "heading":
            new_zone = ZONE_BODY

        # -----------------------------------------------------
        # DEFAULTS OUTSIDE TITLE PAGE
        # -----------------------------------------------------
        if new_zone is None:
            if current_zone is None:
                # after title_page, default to body
                if title_end is not None and block_index > title_end:
                    new_zone = ZONE_BODY
                else:
                    new_zone = ZONE_FRONT_MATTER
            else:
                extend_zone(block_index)
                continue

        if current_zone is None:
            start_zone(new_zone, block_index)
            continue

        if new_zone == current_zone:
            extend_zone(block_index)
            continue

        flush()
        start_zone(new_zone, block_index)

    flush()

    with repo.conn.cursor() as cur:
        cur.execute(
            "delete from du_zone_hypotheses where document_id = %s",
            (document_id,),
        )

        cur.executemany(
            """
            insert into du_zone_hypotheses
            (
                document_id,
                zone_type,
                start_block_index,
                end_block_index,
                score,
                source
            )
            values (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    document_id,
                    zone_type,
                    start_block_index,
                    end_block_index,
                    score,
                    "inference.zone_hypotheses",
                )
                for zone_type, start_block_index, end_block_index, score in hypotheses
            ],
        )

    repo.conn.commit()
