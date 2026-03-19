from __future__ import annotations

import re


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _normalize_title(text: str | None) -> str | None:
    if text is None:
        return None
    value = _normalize(text).lower()
    return value or None


def _extract_section_number(text: str | None) -> tuple[str | None, bool]:
    value = _normalize(text or "")
    if not value:
        return None, False

    m = re.match(r"^((?:\d+\.)*\d+)\s+.+$", value)
    if m:
        return m.group(1), True

    m = re.match(r"^((?:\d+\.)+\d+)\.?\s*$", value)
    if m:
        return m.group(1), True

    return None, False


def _word_count(text: str) -> int:
    return len((text or "").split())


def _caps_ratio(text: str) -> float:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _looks_sentence_like(text: str) -> bool:
    value = _normalize(text)
    if not value:
        return False
    if _word_count(value) < 6:
        return False
    return value.endswith(".") or value.endswith(";") or value.endswith(":")


def _looks_reference_heading(text: str) -> bool:
    value = _normalize(text).lower()
    return value in {
        "references",
        "bibliography",
        "works cited",
        "literatur",
        "literaturverzeichnis",
        "quellen",
    }


def _is_heading_candidate(text: str) -> bool:
    value = _normalize(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc == 0 or wc > 18:
        return False

    if _looks_sentence_like(value):
        return False

    if value.endswith("."):
        return False

    caps = _caps_ratio(value)
    if value.istitle() and wc <= 12:
        return True
    if caps >= 0.55 and wc <= 12:
        return True
    return wc <= 8


def _infer_level(text: str, is_numbered: bool, section_number: str | None) -> int:
    if is_numbered and section_number:
        return min(section_number.count(".") + 1, 6)

    value = _normalize(text)
    wc = _word_count(value)
    caps = _caps_ratio(value)

    if wc <= 5 and (value.istitle() or caps > 0.60):
        return 1
    if wc <= 10:
        return 2
    return 3


def _fetch_phase_map(repo, document_id: str) -> dict[str, str]:
    cur = repo.conn.cursor()
    cur.execute(
        """
        select
            b.block_id,
            case
                when coalesce(c.front_matter_score, 0.0) >= greatest(
                    coalesce(c.body_score, 0.0),
                    coalesce(c.back_matter_score, 0.0)
                ) then 'front_matter'
                when coalesce(c.back_matter_score, 0.0) >= greatest(
                    coalesce(c.front_matter_score, 0.0),
                    coalesce(c.body_score, 0.0)
                ) then 'back_matter'
                else 'body'
            end as phase
        from du_blocks b
        left join du_block_context c
            on c.block_id = b.block_id
        where b.document_id = %s
        """,
        (document_id,),
    )
    rows = cur.fetchall()
    return {str(block_id): phase for block_id, phase in rows}


def compute_section_tree(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    role_rows = repo.fetch_block_roles(document_id)
    phase_map = _fetch_phase_map(repo, document_id)

    role_map = {str(row["block_id"]): row for row in role_rows}

    headings = []

    for block in blocks:
        block_id = str(block.get("block_id"))
        text = block.get("text") or ""
        role_row = role_map.get(block_id) or {}
        role = role_row.get("role")

        if role == "page_furniture":
            continue

        if phase_map.get(block_id) == "front_matter":
            continue

        if role not in {"heading", "reference"} and not _is_heading_candidate(text):
            continue

        section_number, is_numbered = _extract_section_number(text)
        level = _infer_level(text, is_numbered, section_number)

        headings.append(
            {
                "block_id": block_id,
                "block_index": int(block.get("block_index") or 0),
                "page": block.get("page_index"),
                "title": _normalize(text),
                "title_norm": _normalize_title(text),
                "level": level,
                "phase": phase_map.get(block_id),
                "is_reference_heading": _looks_reference_heading(text),
                "section_number": section_number,
                "is_numbered": is_numbered,
                "role": "reference" if role == "reference" else "heading",
            }
        )

    headings.sort(key=lambda h: h["block_index"])

    nodes = []
    stack: list[dict] = []

    max_block_index = max(
        [int(b.get("block_index") or 0) for b in blocks],
        default=0,
    )

    next_node_id = 1

    for idx, heading in enumerate(headings):
        while stack and stack[-1]["level"] >= heading["level"]:
            stack.pop()

        parent = stack[-1] if stack else None
        next_block_index = (
            headings[idx + 1]["block_index"] if idx + 1 < len(headings) else None
        )

        start_block_index = heading["block_index"]
        end_block_index = (
            next_block_index - 1 if next_block_index is not None else max_block_index
        )

        node = {
            "node_id": next_node_id,
            "parent_id": parent["node_id"] if parent else None,
            "heading_block_id": heading["block_id"],
            "start_block_index": start_block_index,
            "end_block_index": end_block_index,
            "page_start": heading["page"],
            "page_end": heading["page"],
            "level": heading["level"],
            "role": heading["role"],
            "section_number": heading["section_number"],
            "title": heading["title"],
            "title_normalized": heading["title_norm"],
            "is_numbered": heading["is_numbered"],
            "confidence": 0.8,
            "source": "du.section_tree.v2",
        }

        nodes.append(node)
        stack.append(node)
        next_node_id += 1

    repo.store_section_tree(document_id, nodes)
