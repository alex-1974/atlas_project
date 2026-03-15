from __future__ import annotations

import re
import uuid
from typing import List

from atlas.document_understanding.persistence.repository import DURepository
from atlas.document_understanding.roles.block_roles import (
    compute_roles,
    fetch_role_block_map,
)
from atlas.document_understanding.grammar.document_type import (
    infer_document_type,
    fetch_document_grammar_map,
)

# ------------------------------------------------------------
# regex
# ------------------------------------------------------------

INLINE_HEADER = re.compile(r"^(?P<num>\d+(\.\d+)*[a-z]?)\.?\s+(?P<title>.+)$")

HEADER_NUMBER = re.compile(r"^\d+(\.\d+)*[a-z]?\.$")
NUMBER_ONLY = re.compile(r"^\d+(\.\d+)*$")
PAGE_NUMBER = re.compile(r"^\d{1,4}$")

TOC_PATTERN = re.compile(r"\.{3,}|\s\d{1,4}$")

BULLET_PREFIX = re.compile(r"^[\-\u2022]\s+")

# ------------------------------------------------------------
# roles
# ------------------------------------------------------------

HEADING_ROLES = {
    "title_line",
    "section_heading",
    "abstract_heading",
    "appendix_heading",
}

# ------------------------------------------------------------
# utilities
# ------------------------------------------------------------


def cleanup_text(text: str) -> str:
    text = text.strip()

    text = BULLET_PREFIX.sub("", text)

    return text


def is_header_number(text: str) -> bool:
    return bool(HEADER_NUMBER.match(text.strip()))


def is_page_number(text: str) -> bool:
    return bool(PAGE_NUMBER.match(text.strip()))


def level_from_number(num: str) -> int:
    return num.count(".") + 1


def heading_level(role: str):

    if role == "title_line":
        return 0

    if role == "section_heading":
        return 1

    if role == "abstract_heading":
        return 1

    if role == "appendix_heading":
        return 1

    return None


def is_valid_section_title(text: str) -> bool:

    text = text.strip()

    if len(text) < 4:
        return False

    if len(text) > 160:
        return False

    if PAGE_NUMBER.match(text):
        return False

    if NUMBER_ONLY.match(text):
        return False

    if TOC_PATTERN.search(text):
        return False

    words = text.split()

    if len(words) < 2:
        return False

    return True


# ------------------------------------------------------------
# header reconstruction
# ------------------------------------------------------------


def merge_split_headers(blocks: List[dict]) -> List[dict]:

    merged = []

    i = 0
    n = len(blocks)

    while i < n:

        block = blocks[i]
        text = cleanup_text(block["text"])

        if is_page_number(text):
            i += 1
            continue

        if is_header_number(text) and i + 1 < n:

            nxt = blocks[i + 1]

            same_page = block["page_index"] == nxt["page_index"]
            consecutive = nxt["block_index"] == block["block_index"] + 1

            title = cleanup_text(nxt["text"])

            if (
                same_page
                and consecutive
                and title
                and not is_header_number(title)
                and not is_page_number(title)
            ):

                new_block = dict(block)

                new_block["text"] = f"{text} {title}"

                if nxt["role"] in HEADING_ROLES:
                    new_block["role"] = nxt["role"]

                merged.append(new_block)

                i += 2
                continue

        merged.append(block)

        i += 1

    return merged


# ------------------------------------------------------------
# role fetch
# ------------------------------------------------------------


def fetch_role_blocks(repo: DURepository, document_id: str):

    blocks = fetch_role_block_map(repo, document_id)

    roles = compute_roles(blocks)

    rows = []

    for block in blocks:

        block_id = str(block["block_id"])

        rows.append(
            {
                "block_id": block["block_id"],
                "page_index": block["page_index"],
                "block_index": block["block_index"],
                "role": roles[block_id]["role"],
                "text": block["text"] or "",
            }
        )

    rows.sort(key=lambda b: (b["page_index"], b["block_index"]))

    rows = merge_split_headers(rows)

    return rows


# ------------------------------------------------------------
# tree builder
# ------------------------------------------------------------


def build_section_tree(blocks: List[dict], document_type: str):

    if document_type == "toc_or_index":
        return []

    stack = []

    tree = []

    for i, block in enumerate(blocks):

        role = block["role"]

        if role not in HEADING_ROLES:
            continue

        raw_text = cleanup_text(block["text"])

        m = INLINE_HEADER.match(raw_text)

        if m:

            num = m.group("num")

            title = m.group("title").strip()

            if not is_valid_section_title(title):
                continue

            level = level_from_number(num)

            section_title = f"{num} {title}"

        else:

            if not is_valid_section_title(raw_text):
                continue

            level = heading_level(role)

            if level is None:
                continue

            section_title = raw_text

        section_id = str(uuid.uuid4())

        while stack and stack[-1]["level"] >= level:
            stack.pop()

        parent = stack[-1]["section_id"] if stack else None

        node = {
            "section_id": section_id,
            "block_id": block["block_id"],
            "parent_section": parent,
            "level": level,
            "title": section_title[:200],
            "start_block_index": block["block_index"],
            "end_block_index": block["block_index"],
            "page_start": block["page_index"],
            "page_end": block["page_index"],
        }

        tree.append(node)

        stack.append(node)

    # ------------------------------------------------------------
    # span expansion
    # ------------------------------------------------------------

    for idx, node in enumerate(tree):

        end_block_index = node["start_block_index"]
        end_page_index = node["page_start"]

        for later in tree[idx + 1 :]:
            if later["level"] <= node["level"]:
                end_block_index = later["start_block_index"] - 1
                end_page_index = later["page_start"]
                break
        else:

            if blocks:

                end_block_index = blocks[-1]["block_index"]

                end_page_index = blocks[-1]["page_index"]

        if end_block_index < node["start_block_index"]:

            end_block_index = node["start_block_index"]

            end_page_index = node["page_start"]

        node["end_block_index"] = end_block_index

        node["page_end"] = end_page_index

    return tree


# ------------------------------------------------------------
# persistence
# ------------------------------------------------------------


def persist_section_tree(repo: DURepository, document_id: str, tree: List[dict]):

    with repo.conn.cursor() as cur:

        cur.execute(
            """
            delete from du_section_tree
            where document_id = %s
            """,
            (document_id,),
        )

        if not tree:
            repo.conn.commit()
            return

        rows = [
            (
                node["section_id"],
                document_id,
                node["block_id"],
                node["parent_section"],
                node["level"],
                node["title"],
                node["start_block_index"],
                node["end_block_index"],
                node["page_start"],
                node["page_end"],
            )
            for node in tree
        ]

        cur.executemany(
            """
            insert into du_section_tree (
                section_id,
                document_id,
                block_id,
                parent_section,
                level,
                title,
                start_block_index,
                end_block_index,
                page_start,
                page_end
            )
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            rows,
        )

    repo.conn.commit()


# ------------------------------------------------------------
# public API
# ------------------------------------------------------------


def compute_section_tree(repo: DURepository, document_id: str):

    grammar_blocks = fetch_document_grammar_map(repo, document_id)

    document_type = infer_document_type(grammar_blocks)

    role_blocks = fetch_role_blocks(repo, document_id)

    tree = build_section_tree(role_blocks, document_type)

    persist_section_tree(repo, document_id, tree)
