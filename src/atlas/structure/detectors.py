# -----------------------------------------------------------------------------
# LEGACY HEADING HEURISTICS
#
# This module is retained for older segmentation/structure workflows.
# It is NOT the canonical heading detection logic for the current DU pipeline.
#
# Canonical implementation:
#   atlas.document_understanding.core.heading
# -----------------------------------------------------------------------------

"""Score generic block types from cheap structural features."""

from __future__ import annotations

from .features import collect_block_features


def _clip(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _text_from_block(block: list[str] | str) -> str:
    if isinstance(block, str):
        return block
    return "\n".join(block)


def _features_from_block(block: list[str] | str | dict) -> dict:
    if isinstance(block, dict):
        return block
    return collect_block_features(_text_from_block(block))


def score_list_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.55 if f["starts_with_list_marker"] else 0.0
    score += 0.20 if f["starts_with_enumeration"] else 0.0
    score += min(0.20, float(f["line_initial_enumeration_ratio"]) * 0.35)
    score += 0.10 if f["line_count"] >= 2 else 0.0
    score -= 0.20 if f["looks_sentence_like"] else 0.0
    score -= 0.20 if f["contains_doi"] else 0.0
    return _clip(score)


def score_toc_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.45 if f["contains_contents_marker"] else 0.0
    score += min(0.25, float(f["leader_dot_ratio"]) * 0.35)
    score += min(0.22, float(f["line_end_digit_ratio"]) * 0.28)
    score += min(0.18, float(f["short_line_ratio"]) * 0.18)
    score += min(0.18, float(f["line_initial_enumeration_ratio"]) * 0.22)
    score += 0.08 if int(f["line_count"]) >= 3 else 0.0
    score -= 0.22 if f["looks_sentence_like"] and int(f["word_count"]) > 20 else 0.0
    score -= 0.12 if f["contains_doi"] else 0.0
    return _clip(score)


def score_reference_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += min(0.25, float(f["comma_density"]) * 4.0)
    score += min(0.20, float(f["year_density"]) * 40.0)
    score += 0.25 if f["contains_doi"] else 0.0
    score += 0.15 if f["contains_url"] else 0.0
    score += min(0.10, float(f["digit_ratio"]) * 1.2)
    score += min(0.10, float(f["punctuation_ratio"]) * 0.6)
    score -= 0.20 if f["starts_with_list_marker"] else 0.0
    score -= 0.15 if f["section_keyword_score"] >= 0.5 else 0.0
    return _clip(score)


def score_bibliographic_entry_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.35 if f["contains_references_marker"] else 0.0
    score += min(0.22, float(f["year_density"]) * 42.0)
    score += 0.18 if f["contains_doi"] else 0.0
    score += 0.12 if f["contains_url"] else 0.0
    score += min(0.14, float(f["comma_density"]) * 3.0)
    score += min(0.14, int(f["author_initial_pattern_count"]) * 0.08)
    score += 0.08 if int(f["word_count"]) >= 8 else 0.0
    score -= 0.20 if f["looks_sentence_like"] and int(f["word_count"]) > 30 else 0.0
    score -= 0.10 if f["contains_contents_marker"] else 0.0
    return _clip(score)


def score_quote_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.60 if f["contains_quotes"] else 0.0
    score += 0.18 if f["contains_parenthetical_citation"] else 0.0
    score += 0.10 if f["line_count"] >= 2 else 0.0
    score += 0.10 if f["avg_line_length"] < 80 else 0.0
    score -= 0.15 if f["contains_doi"] else 0.0
    score -= 0.10 if f["starts_with_list_marker"] else 0.0
    return _clip(score)


def score_heading_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    words = int(f["word_count"])
    score = 0.0
    score += 0.20 if 1 <= words <= 16 else 0.0
    score += 0.20 if f["line_count"] <= 2 else 0.0
    score += min(0.25, float(f["uppercase_ratio"]) * 0.5)
    score += min(0.20, float(f["titlecase_ratio"]) * 0.4)
    score += 0.20 if f["section_keyword_score"] >= 0.5 else 0.0
    score += 0.10 if f["starts_with_enumeration"] else 0.0
    score -= 0.25 if f["has_terminal_period"] else 0.0
    score -= 0.20 if words > 20 else 0.0
    score -= 0.15 if f["contains_doi"] or f["contains_url"] else 0.0
    return _clip(score)


def score_running_text_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    words = int(f["word_count"])
    score = 0.0
    score += 0.30 if words >= 30 else 0.15 if words >= 12 else 0.0
    score += 0.25 if f["looks_sentence_like"] else 0.0
    score += min(0.15, float(f["lowercase_ratio"]) * 0.2)
    score += min(0.10, float(f["lexical_diversity"]) * 0.1)
    score += min(0.08, int(f["parenthetical_citation_count"]) * 0.04)
    score -= 0.30 if f["starts_with_list_marker"] else 0.0
    score -= 0.25 if f["contains_doi"] else 0.0
    score -= 0.15 if f["trailing_page_number"] else 0.0
    score -= 0.10 if f["section_keyword_score"] >= 0.5 and words < 8 else 0.0
    return _clip(score)


def score_title_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    words = int(f["word_count"])
    score = 0.0
    score += 0.30 if 2 <= words <= 24 else 0.0
    score += 0.20 if f["line_count"] <= 3 else 0.0
    score += min(0.20, float(f["titlecase_ratio"]) * 0.35)
    score += min(0.12, float(f["uppercase_ratio"]) * 0.18)
    score += 0.08 if f["has_terminal_question"] or f["has_terminal_exclamation"] else 0.0
    score -= 0.28 if f["has_terminal_period"] else 0.0
    score -= 0.20 if f["contains_quotes"] else 0.0
    score -= 0.20 if f["contains_doi"] or f["contains_url"] or f["contains_email"] else 0.0
    score -= 0.18 if f["contains_contents_marker"] or f["contains_references_marker"] else 0.0
    score -= 0.15 if f["starts_with_list_marker"] else 0.0
    score -= min(0.20, float(f["negative_title_term_score"]))
    score -= 0.15 if words > 30 else 0.0
    return _clip(score)


def score_date_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.45 if f["contains_full_date"] else 0.0
    score += 0.20 if f["contains_month_name"] else 0.0
    score += 0.12 if f["contains_year"] else 0.0
    score += 0.08 if int(f["word_count"]) <= 16 else 0.0
    score -= 0.18 if f["contains_doi"] or f["contains_url"] else 0.0
    score -= 0.12 if int(f["line_count"]) >= 4 else 0.0
    return _clip(score)


def score_author_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += min(0.35, int(f["author_name_line_count"]) * 0.18)
    score += min(0.20, int(f["author_initial_pattern_count"]) * 0.08)
    score += 0.14 if f["contains_email"] else 0.0
    score += 0.10 if 2 <= int(f["word_count"]) <= 24 else 0.0
    score += 0.08 if int(f["line_count"]) <= 4 else 0.0
    score -= 0.20 if f["contains_doi"] or f["contains_url"] else 0.0
    score -= 0.16 if f["contains_contents_marker"] or f["contains_references_marker"] else 0.0
    score -= 0.12 if f["looks_sentence_like"] and int(f["word_count"]) > 20 else 0.0
    return _clip(score)


def score_affiliation_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.35 if f["contains_affiliation_keyword"] else 0.0
    score += 0.12 if f["contains_email"] else 0.0
    score += 0.10 if 3 <= int(f["word_count"]) <= 28 else 0.0
    score += 0.08 if int(f["line_count"]) <= 4 else 0.0
    score -= 0.18 if f["contains_doi"] or f["contains_url"] else 0.0
    score -= 0.12 if f["contains_contents_marker"] or f["contains_references_marker"] else 0.0
    return _clip(score)


def score_marker_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.28 if f["contains_abstract_marker"] else 0.0
    score += 0.18 if f["contains_keywords_marker"] else 0.0
    score += 0.24 if f["contains_contents_marker"] else 0.0
    score += 0.24 if f["contains_references_marker"] else 0.0
    score += 0.10 if f["section_keyword_score"] >= 0.5 else 0.0
    score += 0.08 if int(f["word_count"]) <= 8 else 0.0
    score -= 0.20 if f["looks_sentence_like"] and int(f["word_count"]) > 15 else 0.0
    return _clip(score)


def score_parenthetical_citation_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.40 if f["contains_parenthetical_citation"] else 0.0
    score += min(0.30, int(f["parenthetical_citation_count"]) * 0.12)
    score += 0.08 if f["looks_sentence_like"] else 0.0
    score -= 0.12 if f["contains_references_marker"] else 0.0
    return _clip(score)


def score_caption_like(block: list[str] | str | dict) -> float:
    f = _features_from_block(block)
    score = 0.0
    score += 0.48 if f["contains_caption_marker"] else 0.0
    score += 0.08 if 2 <= int(f["word_count"]) <= 24 else 0.0
    score += 0.08 if int(f["line_count"]) <= 3 else 0.0
    score -= 0.15 if f["contains_doi"] else 0.0
    score -= 0.10 if f["contains_contents_marker"] else 0.0
    return _clip(score)
