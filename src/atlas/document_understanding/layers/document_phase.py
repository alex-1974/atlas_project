from __future__ import annotations


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _fetch_blocks(repo, document_id: str):
    return repo.fetch_blocks(document_id)


def _fetch_roles(repo, document_id: str):
    cur = repo.conn.cursor()
    cur.execute(
        """
        select b.block_id, r.role
        from du_blocks b
        left join du_block_roles r
            on r.block_id = b.block_id
        where b.document_id = %s
        """,
        (document_id,),
    )
    rows = cur.fetchall()
    return {str(block_id): role for block_id, role in rows}


def _fetch_page_furniture(repo, document_id: str):
    cur = repo.conn.cursor()
    cur.execute(
        """
        select
            b.block_id,
            coalesce(p.page_number_like, false) as page_number_like,
            coalesce(p.running_header_like, false) as running_header_like,
            coalesce(p.running_footer_like, false) as running_footer_like,
            coalesce(p.first_page_meta_like, false) as first_page_meta_like
        from du_blocks b
        left join du_block_page_furniture_signals p
            on p.block_id = b.block_id
        where b.document_id = %s
        """,
        (document_id,),
    )
    rows = cur.fetchall()
    return {
        str(block_id): {
            "page_number_like": bool(page_number_like),
            "running_header_like": bool(running_header_like),
            "running_footer_like": bool(running_footer_like),
            "first_page_meta_like": bool(first_page_meta_like),
        }
        for (
            block_id,
            page_number_like,
            running_header_like,
            running_footer_like,
            first_page_meta_like,
        ) in rows
    }


def _is_back_matter_heading(text: str) -> bool:
    value = _normalize(text)
    return value in {
        "references",
        "bibliography",
        "works cited",
        "literature",
        "literatur",
        "literaturverzeichnis",
        "quellen",
        "appendix",
        "anhang",
    }


def _looks_referenceish(text: str) -> bool:
    low = _normalize(text)
    markers = (
        "doi",
        "vol.",
        "volume",
        "issue",
        "pp.",
        "isbn",
        "issn",
        "publisher",
        "editors",
    )
    return any(marker in low for marker in markers)


def _detect_back_matter_start(blocks, roles):
    for block in blocks:
        block_id = str(block.get("block_id"))
        text = block.get("text") or ""
        role = roles.get(block_id)

        if role == "heading" and _is_back_matter_heading(text):
            return int(block.get("block_index") or 0)

        if role == "reference":
            return int(block.get("block_index") or 0)

        if _looks_referenceish(text):
            return int(block.get("block_index") or 0)

    return None


def compute_document_phase(repo, document_id: str) -> None:
    blocks = _fetch_blocks(repo, document_id)
    roles = _fetch_roles(repo, document_id)
    furniture = _fetch_page_furniture(repo, document_id)

    back_matter_start = _detect_back_matter_start(blocks, roles)

    rows = []

    for block in blocks:
        block_id = str(block.get("block_id"))
        block_index = int(block.get("block_index") or 0)
        role = roles.get(block_id)
        furn = furniture.get(block_id) or {}

        is_page_furniture = (
            furn.get("page_number_like")
            or furn.get("running_header_like")
            or furn.get("running_footer_like")
            or role == "page_furniture"
        )
        is_first_page_meta = bool(furn.get("first_page_meta_like"))

        front = 0.0
        body = 0.0
        back = 0.0

        if is_page_furniture:
            front = 0.0
            body = 0.0
            back = 0.0
        elif is_first_page_meta or role in {"title", "author", "front_matter"}:
            front = 1.0
            body = 0.0
            back = 0.0
        elif back_matter_start is not None and block_index >= back_matter_start:
            front = 0.0
            body = 0.0
            back = 1.0
        elif role == "reference":
            front = 0.0
            body = 0.0
            back = 1.0
        else:
            front = 0.0
            body = 1.0
            back = 0.0

        rows.append((block_id, front, body, back))

    cur = repo.conn.cursor()
    cur.executemany(
        """
        insert into du_block_context (
            block_id,
            front_matter_score,
            body_score,
            back_matter_score,
            updated_at
        )
        values (%s, %s, %s, %s, now())
        on conflict (block_id) do update
        set
            front_matter_score = excluded.front_matter_score,
            body_score = excluded.body_score,
            back_matter_score = excluded.back_matter_score,
            updated_at = now()
        """,
        rows,
    )
    repo.conn.commit()
