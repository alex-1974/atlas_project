# src/atlas/understanding/core/similarity.py
"""String similarity utilities for the Document Understanding pipeline.

Provides a fast, dependency-free implementation of the Damerau-Levenshtein
distance and derived similarity metrics used across DU modules:

  - toc.py     : matching TOC titles against heading block texts
  - headings.py: deduplicating heading candidates
  - section_tree.py: merging overlapping section nodes

All functions operate on pre-normalised lowercase strings (no whitespace,
or word-tokenised).  Callers should normalise before comparing.

Damerau-Levenshtein vs. plain Levenshtein
-----------------------------------------
DL adds transposition of adjacent characters as a primitive operation
(cost 1), which makes it more forgiving for OCR artefacts and common
typos like "teh" → "the".  For section titles this matters because OCR
sometimes swaps adjacent characters in headings.

Performance
-----------
The restricted DL implementation (optimal string alignment) runs in
O(m·n) time and O(min(m,n)) space — fast enough for the title lengths
typical in academic documents (≤ 20 words, ≤ 120 characters).
"""
from __future__ import annotations

import re


# ── Character-level Damerau-Levenshtein ──────────────────────────────────────

def damerau_levenshtein(a: str, b: str) -> int:
    """Compute the restricted Damerau-Levenshtein (optimal string alignment)
    distance between two strings.

    Primitive operations (each cost 1):
      - insertion
      - deletion
      - substitution
      - transposition of two adjacent characters

    Returns 0 for identical strings, max(len(a), len(b)) for completely
    different strings of those lengths.

    Note: the *restricted* variant does not satisfy the triangle inequality,
    but it is faster and sufficient for title matching.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la

    # Use two rows to keep O(min(m,n)) space
    if la < lb:
        a, b, la, lb = b, a, lb, la  # ensure la >= lb

    prev_prev = list(range(lb + 1))
    prev      = [0] * (lb + 1)
    curr      = [0] * (lb + 1)

    for i in range(1, la + 1):
        curr[0] = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j]     + 1,        # deletion
                curr[j - 1] + 1,        # insertion
                prev[j - 1] + cost,     # substitution
            )
            # Transposition
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                curr[j] = min(curr[j], prev_prev[j - 2] + cost)

        prev_prev, prev, curr = prev, curr, [0] * (lb + 1)

    return prev[lb]


def char_similarity(a: str, b: str) -> float:
    """Normalised similarity in [0, 1] based on Damerau-Levenshtein distance.

    1.0 = identical, 0.0 = maximally different.

    sim = 1 - distance / max(len(a), len(b))
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    dist = damerau_levenshtein(a, b)
    return 1.0 - dist / max(len(a), len(b))


# ── Word-level similarity ──────────────────────────────────────────────────────

def word_overlap(a: str, b: str) -> float:
    """Jaccard similarity of word sets.

    Useful for comparing section titles where word order may differ slightly
    but the vocabulary should overlap significantly.

    Returns 0.0 if both strings are empty.
    """
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    intersection = len(wa & wb)
    union        = len(wa | wb)
    return intersection / union


def title_similarity(a: str, b: str) -> float:
    """Combined title similarity for TOC/heading matching.

    Combines character-level DL similarity with word-level Jaccard overlap.
    The combination is weighted toward word overlap for longer titles and
    toward character similarity for shorter titles (≤ 3 words).

    Returns a score in [0, 1].

    Typical thresholds:
      ≥ 0.85  strong match — same section, minor OCR differences
      ≥ 0.65  probable match — same section, different phrasing or truncation
      ≥ 0.45  weak match — may be related sections
      < 0.45  different sections
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    # Normalise: lowercase, collapse whitespace, strip leading section numbers
    na = _norm(a)
    nb = _norm(b)

    if na == nb:
        return 1.0

    char_sim = char_similarity(na, nb)
    word_sim  = word_overlap(na, nb)

    # Weight: for short titles (≤ 3 words) char_sim is more informative;
    # for longer titles word_sim handles truncation better.
    wc = len(na.split())
    if wc <= 3:
        return 0.60 * char_sim + 0.40 * word_sim
    else:
        return 0.35 * char_sim + 0.65 * word_sim


def is_likely_same_section(a: str, b: str, threshold: float = 0.70) -> bool:
    """True if two section titles likely refer to the same section.

    Uses title_similarity with a configurable threshold.
    Default threshold of 0.65 catches most OCR/formatting differences
    while avoiding false positives between different sections.
    """
    return title_similarity(a, b) >= threshold


# ── Helpers ───────────────────────────────────────────────────────────────────

_SECTION_NUM_RE = re.compile(
    r'^(?:\d+(?:\.\d+)*|[ivx]+(?:\.\d+)?|[a-z](?:\.\d+)?)\s+',
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    """Lowercase, collapse whitespace, strip leading section numbers."""
    t = " ".join(text.split()).lower()
    t = _SECTION_NUM_RE.sub("", t)
    return t.strip()
