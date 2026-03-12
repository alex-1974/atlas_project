from atlas.structure.detectors import (
    score_heading_like,
    score_reference_like,
    score_running_text_like,
    score_title_like,
)
from atlas.structure.evidence import compute_block_evidence_dict
from atlas.structure.features import collect_block_features


def test_collect_block_features_basic_flags():
    feats = collect_block_features("References\nSmith, J. 2020. https://example.org")
    assert feats["contains_year"] is True
    assert feats["contains_url"] is True
    assert feats["line_count"] == 2


def test_reference_like_scores_high_for_bibliographic_block():
    text = "Smith, J., Doe, A. (2020). A study on timber framing. Journal of Building History, 12(3), 10-20. https://doi.org/10.1234/abcd"
    assert score_reference_like(text) >= 0.55


def test_running_text_scores_above_heading_for_paragraph():
    text = (
        "This article analyses the distribution of structural elements in a large "
        "corpus of scientific PDFs and compares several generic heuristics for "
        "robust document segmentation across disciplines."
    )
    assert score_running_text_like(text) > score_heading_like(text)


def test_title_like_penalizes_administrative_lines():
    bad = "Department of Internal Medicine, Volume 12, Issue 3"
    good = "Structural Patterns in Early Modern Scientific Publishing"
    assert score_title_like(good) > score_title_like(bad)


def test_evidence_dict_exposes_title_like_and_base_scores():
    evidence = compute_block_evidence_dict("A Generic Method for Document Structure Detection")
    assert "title_like" in evidence
    assert "heading_like" in evidence
