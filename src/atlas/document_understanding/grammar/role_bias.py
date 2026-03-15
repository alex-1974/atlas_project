from __future__ import annotations

from typing import Dict


ROLE_BIAS: dict[str, dict[str, float]] = {

    "journal_article": {
        "title_line": 1.2,
        "author_line": 1.2,
        "abstract_heading": 1.5,
        "abstract_text": 1.4,
        "keyword_line": 1.4,
        "reference_entry": 1.3,
    },

    "report": {
        "section_heading": 1.3,
        "body_text": 1.2,
        "appendix_heading": 1.4,
    },

    "book_chapter": {
        "section_heading": 1.3,
        "body_text": 1.2,
        "reference_entry": 1.1,
    },

    "teaching_material": {
        "section_heading": 1.4,
        "caption": 1.4,
        "body_text": 1.2,
    },

    "toc_or_index": {
        "section_heading": 0.5,
        "body_text": 0.3,
        "reference_entry": 0.2,
    },

    "other": {},
}


def apply_role_bias(
    scores: Dict[str, float],
    document_type: str
) -> Dict[str, float]:

    bias = ROLE_BIAS.get(document_type, {})

    adjusted = {}

    for role, score in scores.items():

        factor = bias.get(role, 1.0)

        adjusted[role] = score * factor

    return adjusted
