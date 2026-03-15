from __future__ import annotations

from typing import Dict, List


def apply_grammar_constraints(blocks: List[dict], roles: Dict[str, dict]) -> Dict[str, dict]:
    """
    Adjust role assignments using document grammar constraints.
    """

    ordered = sorted(blocks, key=lambda b: b["block_index"])

    seen_abstract = False
    seen_keywords = False
    seen_references = False

    for block in ordered:

        block_id = str(block["block_id"])
        role = roles[block_id]["role"]

        text = (block.get("text") or "").lower()

        # detect abstract section
        if role == "abstract_heading":
            seen_abstract = True
            continue

        if seen_abstract and role == "body_text":
            roles[block_id]["role"] = "abstract_text"

        # detect keywords
        if role == "keyword_line":
            seen_keywords = True
            continue

        # after keywords → body
        if seen_keywords and role == "abstract_text":
            roles[block_id]["role"] = "body_text"

        # detect references
        if role == "reference_entry":
            seen_references = True
            continue

        # after references → references dominate
        if seen_references and role == "body_text":
            roles[block_id]["role"] = "reference_entry"

        # appendix heading dominates following headings
        if role == "appendix_heading":
            seen_references = False

    return roles
