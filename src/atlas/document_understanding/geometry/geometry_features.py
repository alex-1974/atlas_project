from __future__ import annotations

from atlas.document_understanding.persistence.repository import DURepository


def compute_geometry(repo: DURepository, document_id: str) -> None:

    blocks = fetch_blocks(repo, document_id)

    if not blocks:
        return

    rows = []

    for i, block in enumerate(blocks):

        prev_block = blocks[i - 1] if i > 0 else None
        next_block = blocks[i + 1] if i < len(blocks) - 1 else None

        text = block["text"]

        length = len(text)

        whitespace_before = 0
        whitespace_after = 0

        if prev_block:
            whitespace_before = block["block_index"] - prev_block["block_index"]

        if next_block:
            whitespace_after = next_block["block_index"] - block["block_index"]

        indent_left = leading_spaces(text)
        indent_right = trailing_spaces(text)

        centeredness = compute_centeredness(text)

        rows.append(
            {
                "block_id": block["block_id"],
                "width": length,
                "height": 1,
                "center_x": None,
                "center_y": None,
                "whitespace_before": whitespace_before,
                "whitespace_after": whitespace_after,
                "indent_left": indent_left,
                "indent_right": indent_right,
                "centeredness": centeredness,
                "column_hint": None,
                "near_page_top": near_page_top(block),
                "near_page_bottom": near_page_bottom(block),
            }
        )

    insert_geometry(repo, rows)


def fetch_blocks(repo: DURepository, document_id):

    with repo.conn.cursor() as cur:

        cur.execute(
            """
            select block_id, block_index, page_index, text
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]

        return [dict(zip(cols, r)) for r in cur.fetchall()]


def insert_geometry(repo: DURepository, rows):

    with repo.conn.cursor() as cur:

        for r in rows:

            cur.execute(
                """
                insert into du_block_geometry (
                    block_id,
                    width,
                    height,
                    center_x,
                    center_y,
                    whitespace_before,
                    whitespace_after,
                    indent_left,
                    indent_right,
                    centeredness,
                    column_hint,
                    near_page_top,
                    near_page_bottom
                )
                values (
                    %(block_id)s,
                    %(width)s,
                    %(height)s,
                    %(center_x)s,
                    %(center_y)s,
                    %(whitespace_before)s,
                    %(whitespace_after)s,
                    %(indent_left)s,
                    %(indent_right)s,
                    %(centeredness)s,
                    %(column_hint)s,
                    %(near_page_top)s,
                    %(near_page_bottom)s
                )
                on conflict (block_id) do nothing
                """,
                r,
            )


def leading_spaces(text: str) -> int:

    count = 0

    for c in text:
        if c == " ":
            count += 1
        else:
            break

    return count


def trailing_spaces(text: str) -> int:

    count = 0

    for c in reversed(text):
        if c == " ":
            count += 1
        else:
            break

    return count


def compute_centeredness(text: str) -> float:

    left = leading_spaces(text)
    right = trailing_spaces(text)

    total = left + right

    if total == 0:
        return 0.0

    return 1.0 - abs(left - right) / total


def near_page_top(block) -> float:

    if block["block_index"] < 5:
        return 1.0

    if block["block_index"] < 15:
        return 0.5

    return 0.0


def near_page_bottom(block) -> float:

    return 0.0
