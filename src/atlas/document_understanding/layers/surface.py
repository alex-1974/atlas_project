# src/atlas/document_understanding/layers/surface.py

from __future__ import annotations

import re

from atlas.document_understanding.persistence.repository import Repository
from atlas.document_understanding.core.coordinate_system import DocumentCoordinateSystem


BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦‣]|\d+[.)]|[A-Za-z][.)])\s+")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
URL_RE = re.compile(r"\bhttps?://\S+\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.[A-Za-z]{2,}\b")
YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


def _letter_stats(text: str) -> tuple[int, int, int]:
    upper = 0
    lower = 0
    letters = 0

    for ch in text:
        if ch.isalpha():
            letters += 1
            if ch.isupper():
                upper += 1
            elif ch.islower():
                lower += 1

    return letters, upper, lower


def _count_words(text: str) -> int:
    return len(text.split())


def _count_sentences(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    return len([p for p in parts if p.strip()])


def _punctuation_density(text: str) -> float:
    if not text:
        return 0.0
    punct = sum(1 for ch in text if ch in ",.;:!?()[]{}\"'“”‘’/-")
    return punct / max(1, len(text))


def _digit_density(text: str) -> float:
    if not text:
        return 0.0
    digits = sum(1 for ch in text if ch.isdigit())
    return digits / max(1, len(text))


def _line_count(text: str) -> int:
    return max(1, len(text.splitlines()))


def _mean_line_length(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    return sum(len(line) for line in lines) / len(lines)


def compute_surface(repository: Repository, doc_id: int) -> None:
    """
    Compute text-surface features.

    This layer is still mostly non-semantic:
    it describes the formal surface shape of text.

    Stored features should be dimensionless and reusable by higher layers.
    """
    blocks = repository.fetch_blocks(doc_id)
    if not blocks:
        return

    coord: DocumentCoordinateSystem = repository.fetch_coordinate_system(doc_id)

    rows: list[dict] = []

    for block in blocks:
        text = (block.get("text") or "").strip()

        char_count = len(text)
        word_count = _count_words(text)
        sentence_count = _count_sentences(text)

        letters, upper, lower = _letter_stats(text)
        capitalization_ratio = _safe_div(upper, letters) if letters else 0.0

        mean_line_length = _mean_line_length(text)
        line_count = _line_count(text)

        x0 = block.get("x0")
        x1 = block.get("x1")
        width = None
        if x0 is not None and x1 is not None:
            width = float(x1) - float(x0)

        line_width_ratio = coord.width_ratio_to_column(width)

        ends_with_period = text.endswith(".")
        ends_with_colon = text.endswith(":")
        starts_with_number = bool(re.match(r"^\s*\d+", text))
        starts_with_bullet = bool(BULLET_RE.match(text))

        contains_parentheses = "(" in text or ")" in text
        contains_brackets = "[" in text or "]" in text
        contains_url = bool(URL_RE.search(text))
        contains_email = bool(EMAIL_RE.search(text))
        contains_doi = bool(DOI_RE.search(text))
        contains_year = bool(YEAR_RE.search(text))

        is_all_caps = bool(letters > 0 and upper == letters)
        is_short_line = bool(word_count <= 12 and (line_width_ratio is not None and line_width_ratio < 0.75))

        rows.append(
            {
                "block_id": block["block_id"],
                "char_count": char_count,
                "word_count": word_count,
                "sentence_count": sentence_count,
                "line_count": line_count,
                "mean_line_length": mean_line_length,
                "line_width_ratio": line_width_ratio,
                "capitalization_ratio": capitalization_ratio,
                "punctuation_density": _punctuation_density(text),
                "digit_density": _digit_density(text),
                "ends_with_period": ends_with_period,
                "ends_with_colon": ends_with_colon,
                "starts_with_number": starts_with_number,
                "starts_with_bullet": starts_with_bullet,
                "contains_parentheses": contains_parentheses,
                "contains_brackets": contains_brackets,
                "contains_url": contains_url,
                "contains_email": contains_email,
                "contains_doi": contains_doi,
                "contains_year": contains_year,
                "is_all_caps": is_all_caps,
                "is_short_line": is_short_line,
            }
        )

    repository.store_surface_features(doc_id, rows)
