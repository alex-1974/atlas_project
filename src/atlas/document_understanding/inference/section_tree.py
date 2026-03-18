from __future__ import annotations

import re


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _normalize_title(text: str | None) -> str | None:
    if text is None:
        return None
    value = _normalize(text)
    if not value:
        return None
    return value.lower()


def _extract_section_number(text: str | None) -> tuple[str | None, bool]:
    if not text:
        return None, False

    value = _normalize(text)

    m = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+", value)
    if m:
        return m.group(1), True

    m = re.match(r"^([IVXLCDM]+)(?:[.)])?\s+", value)
    if m:
        return m.group(1), True

    return None, False


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _looks_sentence_like(text: str) -> bool:
    wc = _word_count(text)
    if wc >= 12:
        return True
    if wc >= 6 and ("," in text or text.endswith(".")):
        return True
    return False


def _is_referenceish(text: str) -> bool:
    low = text.lower()
    return any(
        k in low
        for k in (
            "journal",
            "press",
            "vol.",
            "doi",
            "council",
            "archaeology",
            "bibliography",
            "references",
            "va ",
        )
    )


def _is_running_header(text: str) -> bool:
    if re.match(r"^\d+\s+[A-Z]", text):
        return True
    if _caps_ratio(text) > 0.7 and any(c.isdigit() for c in text):
        return True
    return False


def _looks_reference_heading(text: str) -> bool:
    low = text.lower().strip()
    return low in {
        "references",
        "bibliography",
        "works cited",
        "literatur",
        "literaturverzeichnis",
        "acknowledgements",
        "appendix",
    }


def _is_heading_candidate(text: str) -> bool:
    text = _normalize(text)
    if not text:
        return False

    wc = _word_count(text)

    if _is_running_header(text):
        return False

    if _is_referenceish(text) and wc > 4:
        return False

    if _looks_sentence_like(text) and not text.endswith(":"):
        return False

    if text.endswith(":") and wc <= 12:
        return True

    if wc <= 3 and not _looks_sentence_like(text):
        return True

    if wc <= 6 and text.istitle():
        return True

    if _caps_ratio(text) >= 0.75 and wc <= 10:
        return True

    return False


def _infer_level(text: str, is_numbered: bool, section_number: str | None) -> int:
    text = _normalize(text)
    wc = _word_count(text)

    if is_numbered and section_number:
        if "." in section_number:
            return min(4, section_number.count(".") + 1)
        return 1

    if text.endswith(":"):
        return 2

    if wc <= 2:
        return 2

    if _caps_ratio(text) > 0.75:
        return 1

    return 3


def _detect_reference_region_start(roles: list[dict], block_map: dict[str, dict]) -> int | None:
    """
    Detect beginning of references/back matter.

    Strategy:
    - explicit reference-like heading wins
    - otherwise a late cluster of reference/body bibliographic lines
    """
    candidate_rows = sorted(
        roles,
        key=lambda r: int(block_map.get(str(r["block_id"]), {}).get("block_index") or 0)
    )

    explicit = None
    for row in candidate_rows:
        block = block_map.get(str(row["block_id"]))
        if not block:
            continue
        text = _normalize(block.get("text") or "")
        block_index = int(block.get("block_index") or 0)

        if _looks_reference_heading(text):
            explicit = block_index
            break

    if explicit is not None:
        return explicit

    # fallback: late referenceish cluster
    late = []
    max_block = max((int(b.get("block_index") or 0) for b in block_map.values()), default=0)
    late_threshold = max(20, int(max_block * 0.55))

    for row in candidate_rows:
        block = block_map.get(str(row["block_id"]))
        if not block:
            continue
        text = _normalize(block.get("text") or "")
        block_index = int(block.get("block_index") or 0)
        role = row.get("role")

        if block_index < late_threshold:
            continue

        refish = role == "reference" or _is_referenceish(text)
        if refish:
            late.append(block_index)

    if len(late) >= 4:
        return min(late)

    return None


def compute_section_tree(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    roles = repo.fetch_block_roles(document_id)

    if not blocks or not roles:
        repo.store_section_tree(document_id, [])
        return

    block_map = {str(b["block_id"]): b for b in blocks}
    max_block = max(int(b["block_index"]) for b in blocks)

    reference_start = _detect_reference_region_start(roles, block_map)

    headings: list[dict] = []

    for row in roles:
        block_id = str(row["block_id"])
        block = block_map.get(block_id)
        if not block:
            continue

        text = _normalize(block.get("text") or "")
        if not text:
            continue

        role = row.get("role")
        block_index = int(block["block_index"])
        page_index = block.get("page_index")

        # 1) title blocks at the document start are NOT section tree nodes
        if role == "title" and block_index <= 8:
            continue

        # 2) once references start, only explicit reference headings survive
        if reference_start is not None and block_index >= reference_start:
            if not _looks_reference_heading(text):
                continue

        # 3) only heading/title roles are even considered
        if role not in ("heading", "title"):
            continue

        if not _is_heading_candidate(text):
            continue

        section_number, is_numbered = _extract_section_number(text)
        level = _infer_level(text, is_numbered, section_number)

        headings.append(
            {
                "block_id": block["block_id"],
                "block_index": block_index,
                "page_index": page_index,
                "text": text,
                "level": level,
                "section_number": section_number,
                "is_numbered": is_numbered,
            }
        )

    if not headings:
        repo.store_section_tree(document_id, [])
        return

    headings.sort(key=lambda x: x["block_index"])

    nodes = []
    stack = []

    for i, h in enumerate(headings):
        start = h["block_index"]
        end = headings[i + 1]["block_index"] - 1 if i + 1 < len(headings) else max_block

        while stack and stack[-1]["level"] >= h["level"]:
            stack.pop()

        parent = stack[-1]["node_id"] if stack else None

        node = {
            "node_id": i + 1,
            "parent_id": parent,
            "heading_block_id": h["block_id"],
            "start_block_index": start,
            "end_block_index": end,
            "page_start": h["page_index"],
            "page_end": h["page_index"],
            "level": h["level"],
            "role": "heading",
            "section_number": h["section_number"],
            "title": h["text"],
            "title_normalized": _normalize_title(h["text"]),
            "is_numbered": h["is_numbered"],
            "confidence": 0.7,
            "source": "section_tree_v5",
        }

        nodes.append(node)
        stack.append(node)

    repo.store_section_tree(document_id, nodes)
