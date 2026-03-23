# src/atlas/document_understanding/core/style_model.py

from __future__ import annotations

from typing import Any


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


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _style_key(h: dict[str, Any]) -> tuple[float, bool]:
    return (
        round(_safe_float(h.get("font_size")), 1),
        bool(h.get("italic")),
    )


# ------------------------------------------------------------
# STYLE CLUSTERING
# ------------------------------------------------------------

def build_style_clusters(headings: list[dict[str, Any]]) -> dict:
    clusters: dict[tuple, list] = {}

    for h in headings:
        key = _style_key(h)
        clusters.setdefault(key, []).append(h)

    return clusters


# ------------------------------------------------------------
# STYLE FEATURES
# ------------------------------------------------------------

def compute_style_features(cluster: list[dict[str, Any]]) -> dict:
    indices = [_safe_int(h.get("block_index")) for h in cluster]
    texts = [_norm(h.get("text")) for h in cluster]

    lengths = [len(t.split()) for t in texts if t]

    return {
        "count": len(cluster),
        "first_index": min(indices) if indices else 10**9,
        "avg_length": sum(lengths) / len(lengths) if lengths else 0,
        "max_font": max(_safe_float(h.get("font_size")) for h in cluster),
    }


# ------------------------------------------------------------
# STYLE SCORING (core logic)
# ------------------------------------------------------------

def score_style(features: dict) -> float:
    """
    Higher score = more likely L1
    """

    score = 0.0

    # earlier in document → more likely main section
    score += max(0, 1.0 - features["first_index"] / 2000)

    # larger font → more important
    score += features["max_font"] * 0.05

    # shorter headings → more likely section titles
    if features["avg_length"] < 6:
        score += 0.5

    # frequent styles are structural
    if features["count"] >= 3:
        score += 0.3

    return score


# ------------------------------------------------------------
# BUILD STYLE MODEL
# ------------------------------------------------------------

def build_style_model(headings: list[dict[str, Any]]) -> dict:
    clusters = build_style_clusters(headings)

    style_scores = {}
    style_features = {}

    for style, cluster in clusters.items():
        features = compute_style_features(cluster)
        score = score_style(features)

        style_scores[style] = score
        style_features[style] = features

    # sort styles → L1, L2, L3...
    ordered_styles = sorted(
        style_scores.keys(),
        key=lambda s: -style_scores[s],
    )

    style_levels = {
        style: i + 1
        for i, style in enumerate(ordered_styles)
    }

    return {
        "clusters": clusters,
        "scores": style_scores,
        "levels": style_levels,
        "features": style_features,
    }
