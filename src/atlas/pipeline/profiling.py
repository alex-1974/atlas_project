# src/atlas/pipeline/profiling.py
"""Pass 0 — Document Pre-Classification.

Determines a DocumentProfile *before* the DU pipeline runs.
The profile drives quadrant-specific signal weights in the
Aggregate layer (signals.py) and zone expectations in the
Interpret layer (zones.py).

Two primary axes, both as fuzzy scores in [0.0, 1.0]:

    book_score      Derived purely from page_count.
                    0 = definitely not a book (short document)
                    1 = definitely a book (long document)

    structure_score Derived from markword_count and font_size_variety.
                    0 = unstructured (essay, novel, plain report)
                    1 = highly structured (manual, textbook, thesis)

The axes are intentionally narrow in their signal sources so they
remain stable, comparable across corpora, and independently tunable
via ground truth.

Additional evidence (PDF outline, roman pagination) is stored as
separate boost scores [0.0, 1.0].  These do NOT feed into the axes.
They are available downstream as tiebreakers or additional weights.

Four quadrants (derived from axes, not hard-coded):

    book_score >= 0.5, structure_score >= 0.5  →  book_structured
    book_score >= 0.5, structure_score <  0.5  →  book_unstructured
    book_score <  0.5, structure_score >= 0.5  →  doc_structured
    book_score <  0.5, structure_score <  0.5  →  doc_unstructured

All fuzzy operations use atlas.core.fuzzy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from atlas.core.fuzzy import flinear, fdampen

from atlas.understanding.core.section_labels import (
    ABSTRACT_HEADINGS,
    REFERENCE_HEADINGS,
    TOC_HEADINGS,
    APPENDIX_HEADINGS,
    KEYWORDS_HEADINGS,
)


# ── Constants ─────────────────────────────────────────────────────────────────

# Pages scanned for font-size variety and roman pagination
_SCAN_PAGES_TYPOGRAPHY = 5

# Pages scanned for roman pagination signals
_SCAN_PAGES_ROMAN = 4

# Structural markwords — union of all anchor headings from section_labels.py
# These signal intentional document structure (not body content).
_STRUCTURE_MARKWORDS: frozenset[str] = (
    ABSTRACT_HEADINGS
    | REFERENCE_HEADINGS
    | TOC_HEADINGS
    | APPENDIX_HEADINGS
    | KEYWORDS_HEADINGS
)

# Roman numeral pattern — matches standalone roman page numbers
# Covers i–xlix (enough for any realistic front matter)
_ROMAN_RE: re.Pattern = re.compile(
    r"""
    ^\s*                        # optional leading whitespace
    (M{0,3})                    # thousands
    (CM|CD|D?C{0,3})            # hundreds
    (XC|XL|L?X{0,3})            # tens
    (IX|IV|V?I{0,3})            # ones
    \s*$                        # optional trailing whitespace
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Must match at least one numeral to avoid matching empty string
_ROMAN_MIN_LEN = 1


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class DocumentProfile:
    """Pre-classification result for a single PDF.

    Primary axes  (narrow, stable, independently tunable)
    -----------------------------------------------------
    book_score      [0;1]  derived from page_count only.
    structure_score [0;1]  derived from markword_count + font_size_variety.

    Boost scores  (additional evidence, stored separately)
    ------------------------------------------------------
    outline_boost   [0;1]  0.8 if PDF has embedded outline, else 0.0.
    roman_boost     [0;1]  0.7 if roman pagination detected, else 0.0.

    These boosts do NOT feed into book_score or structure_score.
    They are available for downstream use — e.g. tiebreaking in
    runner.py, or as extra features for weight optimisation.

    Raw signals  (for debugging and threshold tuning)
    -------------------------------------------------
    page_count        Total pages.
    has_pdf_outline   True if the PDF contains an embedded outline/TOC.
    has_roman_pages   True if roman numerals detected in early pages.
    markword_count    Number of distinct structural markword categories found.
    font_size_variety Distinct font sizes observed on first N pages.
    """

    # Primary axes
    book_score:      float
    structure_score: float

    # Boost scores (separate — do not mix with axes)
    outline_boost: float
    roman_boost:   float

    # Raw signals
    page_count:        int
    has_pdf_outline:   bool
    has_roman_pages:   bool
    markword_count:    int
    font_size_variety: int

    # Derived quadrant label (informational only — not used for logic)
    quadrant: str = field(init=False)

    def __post_init__(self) -> None:
        b = self.book_score >= 0.5
        s = self.structure_score >= 0.5
        if b and s:
            self.quadrant = "book_structured"
        elif b and not s:
            self.quadrant = "book_unstructured"
        elif not b and s:
            self.quadrant = "doc_structured"
        else:
            self.quadrant = "doc_unstructured"

    def __repr__(self) -> str:
        return (
            f"DocumentProfile("
            f"quadrant={self.quadrant!r}, "
            f"book={self.book_score:.2f}, "
            f"structure={self.structure_score:.2f}, "
            f"outline_boost={self.outline_boost:.1f}, "
            f"roman_boost={self.roman_boost:.1f}, "
            f"pages={self.page_count}, "
            f"markwords={self.markword_count}, "
            f"fonts={self.font_size_variety})"
        )


# ── Public entry point ────────────────────────────────────────────────────────

def profile_document(pdf_path: Path) -> DocumentProfile:
    """Compute a DocumentProfile for *pdf_path* without running DU.

    Opens the PDF once, extracts all signals in a single pass,
    then computes fuzzy scores.  Should complete in < 1 s for
    most documents.

    Parameters
    ----------
    pdf_path : Path
        Absolute path to the PDF file.

    Returns
    -------
    DocumentProfile
    """
    doc = fitz.open(str(pdf_path))
    try:
        page_count        = doc.page_count
        has_pdf_outline   = _detect_outline(doc)
        has_roman_pages   = _detect_roman_pagination(doc)
        markword_count    = _count_markwords(doc)
        font_size_variety = _count_font_sizes(doc)
    finally:
        doc.close()

    book_score      = _compute_book_score(page_count)
    structure_score = _compute_structure_score(
        markword_count, font_size_variety, page_count
    )
    outline_boost   = 0.8 if has_pdf_outline else 0.0
    roman_boost     = 0.7 if has_roman_pages else 0.0

    return DocumentProfile(
        book_score=book_score,
        structure_score=structure_score,
        outline_boost=outline_boost,
        roman_boost=roman_boost,
        page_count=page_count,
        has_pdf_outline=has_pdf_outline,
        has_roman_pages=has_roman_pages,
        markword_count=markword_count,
        font_size_variety=font_size_variety,
    )


# ── Fuzzy scoring ─────────────────────────────────────────────────────────────

def _compute_book_score(page_count: int) -> float:
    """Fuzzy score for the Buch/Nicht-Buch axis.

    Signal: page_count only.

    Thresholds (tunable via ground truth):
        lo=30   → score 0.0  (short document, definitely not a book)
        hi=150  → score 1.0  (long document, very likely a book)

    The fuzzy region 30–150 covers genuine ambiguity:
    long reports, theses, extended studies.
    Outline and roman pagination are stored as separate boosts
    and do not influence this score.
    """
    return flinear(page_count, lo=30, hi=150)


def _compute_structure_score(
    markword_count: int,
    font_size_variety: int,
    page_count: int,
) -> float:
    """Fuzzy score for the strukturiert/unstrukturiert axis.

    Signals: markword_count (dominant) and font_size_variety (secondary).

    Combination: weighted sum — markword_count carries 70% of the weight,
    font_size_variety 30%.  This reflects the semantic hierarchy:
    structural markwords (Abstract, References, TOC) are intentional
    signals of document organisation; font variety is a weaker,
    indirect indicator that can fire on visually rich but unstructured
    documents (e.g. scanned historical essays).

    A document with no markwords can reach at most 0.30 — landing in
    doc_unstructured unless font variety is extremely high.
    A document with 1 markword reaches 0.7×0.33 + 0.3×x ≈ 0.53+ —
    enough for doc_structured.

    Short documents (< 5 pages) are dampened — a 3-page document
    with one heading and multiple font sizes is not meaningfully
    structured in the sense relevant for DU zone expectations.

    Thresholds (tunable via ground truth):
        markword_count:    lo=0, hi=3  weight=0.7
        font_size_variety: lo=1, hi=5  weight=0.3
        short-doc dampen:  page_count < 5 → fdampen by 0.5
    """
    markword_signal = flinear(markword_count,    lo=0, hi=3)
    font_signal     = flinear(font_size_variety, lo=1, hi=5)

    score = 0.7 * markword_signal + 0.3 * font_signal

    if page_count < 5:
        score = fdampen(score, 0.5)

    return min(1.0, score)


# ── Signal extractors ─────────────────────────────────────────────────────────

def _detect_outline(doc: fitz.Document) -> bool:
    """True if the PDF has an embedded outline (bookmarks / TOC)."""
    toc = doc.get_toc()
    return len(toc) > 0


def _detect_roman_pagination(doc: fitz.Document) -> bool:
    """True if roman numerals appear as page numbers in early pages.

    Scans page headers and footers (top/bottom 8% of each page)
    on the first _SCAN_PAGES_ROMAN pages.  Requires at least two
    consecutive roman-numeral pages to avoid false positives from
    list items or footnote markers.
    """
    hits = 0
    pages_to_scan = min(_SCAN_PAGES_ROMAN, doc.page_count)

    for page_idx in range(pages_to_scan):
        page   = doc[page_idx]
        height = page.rect.height
        band   = height * 0.08  # top and bottom 8%

        # Header band
        header_clip = fitz.Rect(0, 0, page.rect.width, band)
        # Footer band
        footer_clip = fitz.Rect(0, height - band, page.rect.width, height)

        for clip in (header_clip, footer_clip):
            text = page.get_text("text", clip=clip).strip()
            for token in text.split():
                token_clean = token.strip(".,;:()")
                if (
                    len(token_clean) >= _ROMAN_MIN_LEN
                    and _ROMAN_RE.match(token_clean)
                    and token_clean.lower() not in {"i"}  # too ambiguous alone
                ):
                    hits += 1
                    break  # one hit per band per page is enough

    # Require at least 2 pages with roman hits to avoid false positives
    return hits >= 2


def _count_markwords(doc: fitz.Document) -> int:
    """Count distinct structural markword categories found in the document.

    Returns the number of *categories* matched (max 5), not raw
    occurrence count — stable across documents of different lengths.

    Matching strategy:
    - exact match:      "references"
    - startswith:       "4 references", "references:"
    - contains (≤60c):  "notes and references" — composite headings
                        The length guard prevents false positives
                        from body text that happens to contain a
                        markword in passing.

    Categories: abstract, references, toc, appendix, keywords.
    """
    found: set[str] = set()

    category_map = {
        "abstract":   ABSTRACT_HEADINGS,
        "references": REFERENCE_HEADINGS,
        "toc":        TOC_HEADINGS,
        "appendix":   APPENDIX_HEADINGS,
        "keywords":   KEYWORDS_HEADINGS,
    }

    for page_idx in range(doc.page_count):
        if len(found) == len(category_map):
            break

        page   = doc[page_idx]
        blocks = page.get_text("blocks")

        for block in blocks:
            if block[6] != 0:  # skip image blocks
                continue
            text = _normalize(block[4])
            for category, headings in category_map.items():
                if category in found:
                    continue
                if any(
                    text == h
                    or text.startswith(h)
                    or (len(text) <= 60 and h in text)
                    for h in headings
                ):
                    found.add(category)
                    break

    return len(found)


def _count_font_sizes(doc: fitz.Document) -> int:
    """Count distinct rounded font sizes on the first N pages.

    Rounds to nearest 0.5pt to avoid counting micro-variations
    as distinct sizes.  Returns count of distinct sizes found.
    """
    sizes: set[float] = set()
    pages_to_scan = min(_SCAN_PAGES_TYPOGRAPHY, doc.page_count)

    for page_idx in range(pages_to_scan):
        page  = doc[page_idx]
        spans = page.get_text("dict")["blocks"]

        for block in spans:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    if size > 0:
                        # Round to nearest 0.5pt
                        rounded = round(size * 2) / 2
                        sizes.add(rounded)

    return len(sizes)


# ── Text normalisation ────────────────────────────────────────────────────────

_LETTER_SPACED_RE: re.Pattern = re.compile(
    r"(?<!\w)(\w)(?: (\w))+(?!\w)"
)


def _collapse_letter_spacing(text: str) -> str:
    """Collapse letter-spaced words into normal words.

    'N O T E S  A N D  R E F E R E N C E S'  →  'NOTES AND REFERENCES'

    Matches sequences of single characters separated by single spaces
    that are not adjacent to other word characters.  Multiple spaces
    between letter-spaced words (as is common in print) are preserved
    as single spaces after lowercasing and whitespace normalisation.
    """
    return _LETTER_SPACED_RE.sub(lambda m: m.group(0).replace(" ", ""), text)


def _normalize(text: str) -> str:
    """Lowercase, collapse letter-spacing, normalise whitespace.

    Diacritics are preserved — section_labels.py contains accented forms.
    """
    text = _collapse_letter_spacing(text)
    text = text.strip().lower()
    return " ".join(text.split())
