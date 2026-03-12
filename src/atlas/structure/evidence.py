"""Block evidence aggregation.

Combines structural detectors into a single evidence dictionary
used by block scoring and region assembly.
"""

from __future__ import annotations

from .features import collect_block_features
from .detectors import (
    score_list_like,
    score_toc_like,
    score_reference_like,
    score_bibliographic_entry_like,
    score_quote_like,
    score_heading_like,
    score_running_text_like,
    score_title_like,
    score_date_like,
    score_author_like,
    score_affiliation_like,
    score_marker_like,
    score_parenthetical_citation_like,
    score_caption_like,
)


def compute_block_evidence_dict(text: str) -> dict[str, float]:
    """
    Compute structural evidence scores for a text block.

    Features are computed once and then reused across all detectors.
    """

    features = collect_block_features(text)

    evidence = {
        "list_like": score_list_like(features),
        "toc_like": score_toc_like(features),
        "reference_like": score_reference_like(features),
        "bibliographic_entry_like": score_bibliographic_entry_like(features),
        "quote_like": score_quote_like(features),
        "heading_like": score_heading_like(features),
        "running_text_like": score_running_text_like(features),
        "title_like": score_title_like(features),
        "date_like": score_date_like(features),
        "author_like": score_author_like(features),
        "affiliation_like": score_affiliation_like(features),
        "marker_like": score_marker_like(features),
        "parenthetical_citation_like": score_parenthetical_citation_like(features),
        "caption_like": score_caption_like(features),
    }

    return evidence
