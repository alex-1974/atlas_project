from __future__ import annotations

from atlas.document_understanding.inference.early_meta import detect_early_meta_signals


PRIMARY_TYPES = (
    "journal_article",
    "book_or_chapter",
    "report",
    "thesis",
    "magazine_article",
    "essay",
    "archival_text",
    "other",
)

AMBIGUITY_MARGIN_THRESHOLD = 0.12
LOW_CONFIDENCE_THRESHOLD = 0.45


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _score_structure_density(heading_count: int, max_level: int, total_blocks: int) -> float:
    if total_blocks <= 0:
        return 0.0
    heading_ratio = heading_count / max(total_blocks, 1)
    return min(1.0, heading_ratio * 8.0 + max_level * 0.12)


def _score_reference_density(reference_count: int, total_blocks: int) -> float:
    if total_blocks <= 0:
        return 0.0
    return min(1.0, reference_count / max(total_blocks * 0.12, 1.0))


def _has_degree_or_submission_markers(text: str) -> bool:
    return _contains_any(
        text,
        (
            "submitted to",
            "submitted in partial fulfillment",
            "in partial fulfillment",
            "for the degree of",
            "degree of doctor",
            "degree of master",
            "doctor of philosophy",
            "master of science",
            "master of arts",
            "ph.d.",
            "phd thesis",
            "doctoral thesis",
            "doctoral dissertation",
            "dissertation submitted",
            "eingereicht an",
            "zur erlangung",
            "zur erlangung des",
            "zur erlangung der",
            "dissertation zur",
            "inaugural-dissertation",
            "habilitationsschrift",
            "masterarbeit",
            "diplomarbeit",
        ),
    )


def _has_university_markers(text: str) -> bool:
    return _contains_any(
        text,
        (
            "university",
            "faculty",
            "department",
            "school of",
            "college of",
            "fakultät",
            "universität",
            "institut für",
            "department of",
            "graduate school",
        ),
    )


def _safe_secondary(ranked: list[tuple[str, float]]) -> tuple[str | None, float]:
    if len(ranked) > 1:
        return ranked[1][0], float(ranked[1][1])
    return None, 0.0


def compute_document_type(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    roles = repo.fetch_block_roles(document_id)
    zones = repo.fetch_semantic_zones(document_id)
    tree = repo.fetch_section_tree(document_id)

    if not blocks or not roles:
        scores = {doc_type: 0.0 for doc_type in PRIMARY_TYPES}
        scores["other"] = 1.0
        weights = {doc_type: (1.0 if doc_type == "other" else 0.0) for doc_type in PRIMARY_TYPES}
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        repo.store_document_type_decision(
            document_id,
            primary_type="other",
            secondary_type=None,
            margin=1.0,
            confidence=1.0,
            ambiguous=False,
        )
        repo.store_document_type_scores(document_id, scores, weights, ranked)
        return

    role_counts: dict[str, int] = {}
    for row in roles:
        role = row.get("role")
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1

    total_blocks = len(blocks)
    heading_count = role_counts.get("heading", 0)
    reference_count = role_counts.get("reference", 0)
    caption_count = role_counts.get("caption", 0)
    author_count = role_counts.get("author", 0)
    title_count = role_counts.get("title", 0)

    has_title_page = any(z.get("zone_type") == "title_page" for z in zones)
    has_front_matter = any(z.get("zone_type") == "front_matter" for z in zones)
    has_references_zone = any(z.get("zone_type") == "references" for z in zones)
    has_abstract_zone = any(z.get("zone_type") == "abstract" for z in zones)
    has_toc_zone = any(z.get("zone_type") == "toc" for z in zones)
    has_appendix_zone = any(z.get("zone_type") == "appendix" for z in zones)

    early_text = " ".join((b.get("text") or "") for b in blocks[:30]).lower()
    sample_text = " ".join((b.get("text") or "") for b in blocks[:200]).lower()
    tail_text = " ".join((b.get("text") or "") for b in blocks[-60:]).lower()
    first_12_text = " ".join((b.get("text") or "") for b in blocks[:12]).lower()

    early_meta = detect_early_meta_signals(blocks, limit=10)
    early_journal_meta_count = int(early_meta["journal_meta_count"])
    early_doi_count = int(early_meta["doi_count"])
    early_thesis_marker_count = int(early_meta["thesis_marker_count"])
    early_university_marker_count = int(early_meta["university_marker_count"])
    strong_journal_header = bool(early_meta["strong_journal_header"])
    very_strong_journal_header = bool(early_meta["very_strong_journal_header"])
    strong_thesis_header = bool(early_meta["strong_thesis_header"])

    has_doi = _contains_any(early_text, ("doi:", "doi.org/", "https://doi.org/", "http://doi.org/"))
    has_journal_markers = _contains_any(
        early_text,
        (
            "journal",
            "vol.",
            "volume",
            "issue",
            "pp.",
            "pages",
            "issn",
            "vernacular architecture",
            "transactions of",
            "proceedings of",
        ),
    )
    has_report_word = _contains_any(
        sample_text,
        (
            "report",
            "guidance",
            "guideline",
            "review",
            "white paper",
            "working paper",
            "technical report",
            "research report",
        ),
    )
    has_thesis_word = _contains_any(
        sample_text,
        (
            "thesis",
            "dissertation",
            "doctoral",
            "doctoral thesis",
            "doctoral dissertation",
            "doktorarbeit",
            "habilitation",
            "habilitationsschrift",
            "master thesis",
            "masterarbeit",
            "diplomarbeit",
        ),
    )
    has_book_word = _contains_any(
        sample_text,
        ("chapter", "handbook", "glossary", "principles of", "in this chapter", "edited by"),
    )
    has_magazine_word = _contains_any(
        early_text,
        ("magazine", "newsletter", "bulletin", "gazette", "magazin"),
    )
    has_essay_word = _contains_any(
        sample_text,
        ("essay", "aufsatz", "beitrag", "reflections", "anmerkungen", "bemerkungen"),
    )
    has_archival_word = _contains_any(
        sample_text,
        (
            "archive",
            "archival",
            "manuscript",
            "charter",
            "codex",
            "edition",
            "transcription",
            "urkunde",
            "quelle",
            "quellen",
            "quellenedition",
        ),
    )

    has_degree_submission_markers = _has_degree_or_submission_markers(first_12_text) or _has_degree_or_submission_markers(sample_text)
    has_university_markers = _has_university_markers(first_12_text) or _has_university_markers(sample_text)

    max_level = max((int(node.get("level") or 0) for node in tree), default=0)
    structure_density = _score_structure_density(heading_count, max_level, total_blocks)
    reference_density = _score_reference_density(reference_count, total_blocks)

    looks_like_article_head = bool(
        strong_journal_header
        and title_count >= 1
        and author_count >= 1
    )
    looks_like_real_thesis = bool(
        has_thesis_word
        or has_degree_submission_markers
        or strong_thesis_header
        or (has_university_markers and total_blocks >= 120 and max_level >= 3)
    )

    scores = {doc_type: 0.0 for doc_type in PRIMARY_TYPES}

    # journal_article --------------------------------------------------------
    if has_doi:
        scores["journal_article"] += 3.0
        scores["thesis"] -= 0.8
        scores["book_or_chapter"] -= 0.3

    if has_journal_markers:
        scores["journal_article"] += 1.8

    if early_journal_meta_count >= 2:
        scores["journal_article"] += 1.2

    if strong_journal_header:
        scores["journal_article"] += 2.5
        scores["thesis"] -= 1.0

    if very_strong_journal_header:
        scores["journal_article"] += 2.0
        scores["thesis"] -= 1.2
        scores["report"] -= 0.5

    if looks_like_article_head:
        scores["journal_article"] += 1.6
        scores["thesis"] -= 0.5

    if has_abstract_zone:
        scores["journal_article"] += 0.8

    if has_references_zone:
        scores["journal_article"] += 0.9

    if reference_count >= 5:
        scores["journal_article"] += 0.8

    if has_abstract_zone and has_references_zone and has_doi:
        scores["journal_article"] += 1.0

    if caption_count >= 1:
        scores["journal_article"] += 0.3

    if has_title_page and has_doi and has_journal_markers and author_count >= 1:
        scores["journal_article"] += 1.0
        scores["thesis"] -= 0.5

    if has_report_word:
        scores["journal_article"] -= 1.0

    if looks_like_real_thesis:
        scores["journal_article"] -= 1.5

    if has_book_word:
        scores["journal_article"] -= 0.5

    if has_archival_word:
        scores["journal_article"] -= 0.7

    # thesis ----------------------------------------------------------------
    if has_thesis_word:
        scores["thesis"] += 2.4

    if has_degree_submission_markers:
        scores["thesis"] += 2.6

    if has_university_markers:
        scores["thesis"] += 0.8

    if early_thesis_marker_count >= 1:
        scores["thesis"] += 1.0

    if early_university_marker_count >= 1 and not has_doi and not has_journal_markers:
        scores["thesis"] += 0.5

    if has_title_page and not looks_like_article_head:
        scores["thesis"] += 0.4

    if has_front_matter and not looks_like_article_head:
        scores["thesis"] += 0.3

    if max_level >= 3 and total_blocks >= 120:
        scores["thesis"] += 0.9

    if max_level >= 4 and total_blocks >= 180:
        scores["thesis"] += 0.8

    if total_blocks >= 150:
        scores["thesis"] += 0.7

    if has_appendix_zone:
        scores["thesis"] += 0.3

    if has_journal_markers and has_doi:
        scores["thesis"] -= 1.8

    if strong_journal_header:
        scores["thesis"] -= 0.5

    if very_strong_journal_header:
        scores["thesis"] -= 0.7

    if title_count >= 1 and author_count >= 1 and early_journal_meta_count >= 2:
        scores["thesis"] -= 0.8

    # report ----------------------------------------------------------------
    if has_report_word:
        scores["report"] += 2.3
        scores["essay"] -= 0.5
        scores["magazine_article"] -= 0.3

    if not has_doi:
        scores["report"] += 0.4

    if has_appendix_zone:
        scores["report"] += 0.4

    if structure_density >= 0.5:
        scores["report"] += 0.5

    if has_toc_zone:
        scores["report"] += 0.5

    if very_strong_journal_header:
        scores["report"] -= 0.6

    # book_or_chapter -------------------------------------------------------
    if has_book_word:
        scores["book_or_chapter"] += 2.2
        scores["journal_article"] -= 0.2

    if reference_count >= 5 and not has_doi:
        scores["book_or_chapter"] += 1.1

    if max_level >= 3 and not has_doi:
        scores["book_or_chapter"] += 0.7

    if has_toc_zone:
        scores["book_or_chapter"] += 0.6

    if has_title_page and has_front_matter and not has_doi:
        scores["book_or_chapter"] += 0.4

    # magazine_article ------------------------------------------------------
    if has_magazine_word:
        scores["magazine_article"] += 2.0

    if not has_doi and not has_abstract_zone and reference_count <= 3:
        scores["magazine_article"] += 0.6

    if caption_count > 0 and reference_count <= 2:
        scores["magazine_article"] += 0.2

    if has_report_word:
        scores["magazine_article"] -= 0.4

    if has_thesis_word or has_book_word:
        scores["magazine_article"] -= 0.6

    if very_strong_journal_header:
        scores["magazine_article"] -= 0.8

    # essay -----------------------------------------------------------------
    if has_essay_word:
        scores["essay"] += 2.0

    if not has_doi and not has_abstract_zone and not has_toc_zone:
        scores["essay"] += 0.8

    if 2 <= reference_count <= 12:
        scores["essay"] += 0.6

    if heading_count <= 4 and max_level <= 2:
        scores["essay"] += 0.6

    if has_report_word:
        scores["essay"] -= 0.6

    if looks_like_real_thesis:
        scores["essay"] -= 0.8

    if very_strong_journal_header:
        scores["essay"] -= 0.9

    # archival_text ---------------------------------------------------------
    if has_archival_word:
        scores["archival_text"] += 2.6

    if _contains_any(tail_text, ("edition", "transcription", "editor", "edited by", "source:")):
        scores["archival_text"] += 0.5

    if not has_doi and reference_density < 0.35 and heading_count <= 3:
        scores["archival_text"] += 0.4

    if has_thesis_word or has_journal_markers:
        scores["archival_text"] -= 0.6

    # other -----------------------------------------------------------------
    if total_blocks < 10:
        scores["other"] += 1.0

    if title_count == 0 and author_count == 0 and heading_count == 0 and reference_count == 0:
        scores["other"] += 0.8

    if max(scores.values()) <= 0.6:
        scores["other"] += 0.8

    # Clamp and normalize ---------------------------------------------------
    scores = {key: max(0.0, float(value)) for key, value in scores.items()}
    if sum(scores.values()) == 0.0:
        scores["other"] = 1.0

    total = sum(scores.values())
    weights = {key: value / total for key, value in scores.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

    primary_type, primary_score = ranked[0]
    secondary_type, secondary_score = _safe_secondary(ranked)

    margin = float(primary_score - secondary_score)
    confidence = float(weights.get(primary_type, 0.0))
    ambiguous = bool(
        margin < AMBIGUITY_MARGIN_THRESHOLD
        or (confidence < LOW_CONFIDENCE_THRESHOLD and secondary_score > 0.0)
    )

    repo.store_document_type_decision(
        document_id,
        primary_type=primary_type,
        secondary_type=secondary_type,
        margin=margin,
        confidence=confidence,
        ambiguous=ambiguous,
    )
    repo.store_document_type_scores(document_id, scores, weights, ranked)
