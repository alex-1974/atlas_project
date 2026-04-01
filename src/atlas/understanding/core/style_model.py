# src/atlas/understanding/core/style_model.py
"""Style-Clustering für Heading-Hierarchien.

Gruppiert Heading-Kandidaten nach typografischen Merkmalen und leitet
daraus Hierarchie-Level ab. Wird von interpret/section_tree.py verwendet.

Style-Key umfasst alle typografisch relevanten Achsen:
  (font_size, bold, italic, all_caps, small_caps, color_rank, is_serif)

Damit können L1 (ALL_CAPS, 12pt) und L2 (Title-Case, 12pt) bei gleicher
Fontgröße korrekt unterschieden werden.
"""
from __future__ import annotations

import re
from typing import Any


# ── Safe coercions ────────────────────────────────────────────────────────────

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


# ── Chapter-number level detection ───────────────────────────────────────────

_CHAPTER_NUM_RE = re.compile(
    r'^(?:(\d{1,2})(?:\.(\d{1,3}))?(?:\.(\d{1,3}))?(?:\.(\d{1,3}))?)\s+\S'
)


def chapter_number_level(text: str | None) -> int | None:
    """Return the heading level implied by a chapter number prefix.

    Examples:
        '1 TIMBER CONSTRUCTION'  → 1
        '1.2 Materials'          → 2
        '1.2.1 Lumber'           → 3
        '1.2.1.1 Grading'        → 4
        'Introduction'           → None  (no number prefix)
        'PREFACE'                → None
    """
    t = " ".join((text or "").split()).strip()
    m = _CHAPTER_NUM_RE.match(t)
    if not m:
        return None
    # Count how many groups were captured (each = one level component)
    depth = sum(1 for g in m.groups() if g is not None)
    return max(1, depth)


# ── Style key ─────────────────────────────────────────────────────────────────

def style_key(heading: dict[str, Any]) -> tuple:
    """Rich typographic style key for clustering.

    Axes: (font_size_rounded, bold, italic, all_caps, small_caps,
           color_rank, is_serif)

    All boolean axes are normalised to 0/1 so that missing values
    (None) are treated as 0 rather than a distinct cluster.
    """
    fs         = round(_safe_float(heading.get("font_size")), 1)
    bold       = int(bool(heading.get("bold")))
    italic     = int(bool(heading.get("italic")))
    all_caps   = int(bool(heading.get("all_caps")))
    small_caps = int(bool(heading.get("small_caps")))
    color_rank = _safe_int(heading.get("color_rank"), 0)
    is_serif   = int(bool(heading.get("is_serif")))
    return (fs, bold, italic, all_caps, small_caps, color_rank, is_serif)


# Keep old name as alias for callers that used _style_key directly
_style_key = style_key


# ── Feature extraction ────────────────────────────────────────────────────────

def _compute_style_features(cluster: list[dict[str, Any]]) -> dict:
    indices = [_safe_int(h.get("block_index")) for h in cluster]
    texts   = [" ".join((h.get("text") or "").split()) for h in cluster]
    lengths = [len(t.split()) for t in texts if t]
    return {
        "count":       len(cluster),
        "first_index": min(indices) if indices else 10 ** 9,
        "avg_length":  sum(lengths) / len(lengths) if lengths else 0.0,
        "max_font":    max(_safe_float(h.get("font_size")) for h in cluster),
        "all_caps":    any(bool(h.get("all_caps")) for h in cluster),
        "bold":        any(bool(h.get("bold"))     for h in cluster),
    }


def _score_style(features: dict) -> float:
    """Higher score → more likely L1.

    Signals:
    - Larger font → higher level
    - ALL_CAPS → structural section marker, higher level
    - Bold → prominence
    - Appears early in document → higher level
    - Short average length → heading-like
    - Frequent (≥3) → structural pattern
    """
    score = 0.0
    score += max(0.0, 1.0 - features["first_index"] / 2000)  # early in doc
    score += features["max_font"] * 0.05                       # larger font
    if features["avg_length"] < 6:
        score += 0.5                                           # short headings
    if features["count"] >= 3:
        score += 0.3                                           # recurring pattern
    if features["all_caps"]:
        score += 0.6                                           # ALL_CAPS = top level
    if features["bold"]:
        score += 0.2                                           # bold = prominent
    return score


# ── Public API ────────────────────────────────────────────────────────────────

def build_style_model(headings: list[dict[str, Any]]) -> dict:
    """Build a style model from heading candidates.

    Returns:
        {
            "clusters": {style_key: [heading, ...]},
            "scores":   {style_key: float},
            "levels":   {style_key: int},   # 1 = H1, 2 = H2, ...
            "features": {style_key: dict},
        }

    Note: chapter_number_level() takes precedence over style_levels in
    section_tree.py — this model is only consulted for unnumbered headings.
    """
    clusters: dict[tuple, list] = {}
    for h in headings:
        clusters.setdefault(style_key(h), []).append(h)

    scores   = {s: _score_style(_compute_style_features(c)) for s, c in clusters.items()}
    features = {s: _compute_style_features(c)               for s, c in clusters.items()}

    ordered = sorted(scores, key=lambda s: -scores[s])
    levels  = {style: i + 1 for i, style in enumerate(ordered)}

    # Enforce font-size invariant: a style with larger font_size must not
    # get a higher level number (lower priority) than a style with smaller
    # font_size. L1 >= L2 in font size (or equal, but never L2 > L1).
    # If the score-based ordering violates this, swap the levels.
    #
    # Algorithm: for each pair of styles where font_size(A) > font_size(B)
    # but level(A) > level(B), swap their levels.
    changed = True
    while changed:
        changed = False
        style_list = list(levels.keys())
        for i, sa in enumerate(style_list):
            for sb in style_list[i + 1:]:
                fs_a, fs_b = sa[0], sb[0]  # font_size is first element of style_key
                if fs_a > fs_b and levels[sa] > levels[sb]:
                    # A has larger font but higher level number — swap
                    levels[sa], levels[sb] = levels[sb], levels[sa]
                    changed = True
                elif fs_b > fs_a and levels[sb] > levels[sa]:
                    levels[sa], levels[sb] = levels[sb], levels[sa]
                    changed = True

    return {
        "clusters": clusters,
        "scores":   scores,
        "levels":   levels,
        "features": features,
    }
