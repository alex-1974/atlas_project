# src/atlas/document_understanding/inference/document_model.py
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "t", "true", "True", "yes", "y"):
        return True
    return False


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _alpha_words(text: str) -> list[str]:
    return [w for w in text.split() if any(ch.isalpha() for ch in w)]


def _caps_ratio(text: str | None) -> float:
    t = text or ""
    alpha = [c for c in t if c.isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for c in alpha if c.isupper()) / len(alpha)


def _page_y_ratio(block: dict[str, Any]) -> float | None:
    for key in ("page_y_ratio", "page_y"):
        value = block.get(key)
        if value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= v <= 1.0:
            return v
    return None


def _doc_y_ratio(block: dict[str, Any]) -> float | None:
    for key in ("doc_y_ratio", "doc_y"):
        value = block.get(key)
        if value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= v <= 1.0:
            return v
    return None


def style_key(block: dict[str, Any]) -> str:
    family = (
        block.get("font_family_normalized")
        or block.get("font_family")
        or block.get("font_name")
        or "unknown"
    )
    size = round(_safe_float(block.get("font_size")), 1)
    bold = 1 if _safe_bool(block.get("bold")) else 0
    italic = 1 if _safe_bool(block.get("italic")) else 0
    return f"{family}|{size:.1f}|b{bold}|i{italic}"


def is_page_furniture(block: dict[str, Any]) -> bool:
    if _safe_bool(block.get("is_page_furniture")):
        return True

    if any(
        _safe_bool(block.get(key))
        for key in (
            "page_number_like",
            "running_header_like",
            "running_footer_like",
            "repeated_across_pages",
            "repeated_same_parity",
        )
    ):
        return True

    if _safe_bool(block.get("is_top_band")) and (
        _safe_bool(block.get("running_header_like"))
        or _safe_bool(block.get("page_number_like"))
        or _safe_bool(block.get("repeated_across_pages"))
        or _safe_bool(block.get("repeated_same_parity"))
    ):
        return True

    if _safe_bool(block.get("is_bottom_band")) and (
        _safe_bool(block.get("running_footer_like"))
        or _safe_bool(block.get("page_number_like"))
    ):
        return True

    page_y = _page_y_ratio(block)
    if page_y is not None and (page_y < 0.07 or page_y > 0.93):
        text = _norm(block.get("text"))
        if len(text.split()) <= 12:
            return True

    return False


def is_semantic_exclusion(block: dict[str, Any]) -> bool:
    role = str(block.get("role") or "").strip().lower()
    if role in {"caption", "reference", "noise"}:
        return True

    if _safe_bool(block.get("contains_doi")) or _safe_bool(block.get("semantic_doi")):
        return True

    if _safe_bool(block.get("contains_url")) or _safe_bool(block.get("contains_email")):
        return True

    if _safe_bool(block.get("is_figure_marker")) or _safe_bool(block.get("is_table_marker")):
        return True

    text = _norm(block.get("text")).lower()
    if text.startswith("doi:"):
        return True
    if text.startswith("figure ") or text.startswith("table "):
        return True
    if text.startswith("fig. "):
        return True

    return False


def looks_authorish(block: dict[str, Any]) -> bool:
    role = str(block.get("role") or "").strip().lower()
    if role == "author":
        return True

    text = _norm(block.get("text"))
    words = _alpha_words(text)
    if not 2 <= len(words) <= 10:
        return False

    if any(ch.isdigit() for ch in text):
        return False

    lowered = text.lower()
    if lowered.startswith("doi:"):
        return False
    if "@" in text:
        return False

    titlecase_like = 0
    for word in words:
        core = word.strip(",;:()[]")
        if not core:
            continue
        if core[:1].isupper() and (len(core) == 1 or core[1:].islower()):
            titlecase_like += 1

    centeredness = _safe_float(block.get("centeredness"))
    doc_y = _doc_y_ratio(block)
    near_top = doc_y is not None and doc_y <= 0.22

    if titlecase_like >= max(2, len(words) - 1) and centeredness >= 0.70 and near_top:
        return True

    if " and " in lowered and len(words) <= 10 and centeredness >= 0.60 and near_top:
        return True

    return False


def looks_contactish(block: dict[str, Any]) -> bool:
    text = _norm(block.get("text"))
    lowered = text.lower()

    if "@" in text:
        return True
    if "http://" in lowered or "https://" in lowered or "www." in lowered:
        return True
    if "email" in lowered:
        return True
    if "uk;" in lowered or "usa;" in lowered:
        return True
    if "ntlworld.com" in lowered:
        return True

    return False


def looks_sentence_like(block: dict[str, Any]) -> bool:
    text = _norm(block.get("text"))
    if not text:
        return False

    words = text.split()
    if len(words) >= 16:
        return True

    if text.endswith(".") and len(words) >= 8:
        return True

    lower_start = text[:1].islower()
    if lower_start and len(words) >= 5:
        return True

    punct_density = _safe_float(block.get("punctuation_density"))
    if punct_density >= 0.030 and len(words) >= 10:
        return True

    return False


def is_body_like(block: dict[str, Any]) -> bool:
    if is_page_furniture(block) or is_semantic_exclusion(block) or looks_authorish(block):
        return False

    text = _norm(block.get("text"))
    words = text.split()
    if len(words) < 25:
        return False

    if len(text) < 120:
        return False

    if _safe_bool(block.get("is_all_caps")):
        return False

    if _safe_bool(block.get("italic")) and not _safe_bool(block.get("bold")) and len(words) < 80:
        return False

    if _safe_float(block.get("heading_score")) > _safe_float(block.get("body_score")) + 0.25:
        return False

    return True


def _cluster_summary(style: str, blocks: list[dict[str, Any]], body_style_key: str, max_font_size: float) -> dict[str, Any]:
    sizes = [_safe_float(b.get("font_size")) for b in blocks]
    centeredness = [_safe_float(b.get("centeredness")) for b in blocks]
    doc_ys = [_doc_y_ratio(b) for b in blocks if _doc_y_ratio(b) is not None]
    page_ys = [_page_y_ratio(b) for b in blocks if _page_y_ratio(b) is not None]

    role_counts = Counter(str(b.get("role") or "").lower() for b in blocks)
    furniture_hits = sum(1 for b in blocks if is_page_furniture(b))
    semantic_hits = sum(1 for b in blocks if is_semantic_exclusion(b))
    author_hits = sum(1 for b in blocks if looks_authorish(b))
    contact_hits = sum(1 for b in blocks if looks_contactish(b))
    sentence_hits = sum(1 for b in blocks if looks_sentence_like(b))

    mean_size = sum(sizes) / len(sizes) if sizes else 0.0
    mean_centered = sum(centeredness) / len(centeredness) if centeredness else 0.0
    mean_doc_y = sum(doc_ys) / len(doc_ys) if doc_ys else None
    mean_page_y = sum(page_ys) / len(page_ys) if page_ys else None

    style_role = "unknown"
    if style == body_style_key:
        style_role = "body"
    elif furniture_hits / max(len(blocks), 1) >= 0.50:
        style_role = "furniture"
    elif semantic_hits / max(len(blocks), 1) >= 0.50:
        style_role = "excluded"
    elif author_hits / max(len(blocks), 1) >= 0.50 and mean_centered >= 0.70:
        style_role = "author_candidate"
    elif contact_hits / max(len(blocks), 1) >= 0.40:
        style_role = "contact_candidate"
    elif mean_size >= max_font_size - 0.25 and mean_centered >= 0.75 and (mean_doc_y is None or mean_doc_y < 0.20):
        style_role = "title_candidate"
    elif sentence_hits / max(len(blocks), 1) >= 0.60:
        style_role = "bodyish_variant"
    elif mean_size >= 0.0 and style != body_style_key and furniture_hits == 0 and semantic_hits == 0:
        style_role = "heading_candidate"

    return {
        "style_key": style,
        "font_family": (
            blocks[0].get("font_family_normalized")
            or blocks[0].get("font_family")
            or blocks[0].get("font_name")
        ),
        "font_size": round(mean_size, 1),
        "bold": _safe_bool(blocks[0].get("bold")),
        "italic": _safe_bool(blocks[0].get("italic")),
        "count": len(blocks),
        "page_furniture_ratio": round(furniture_hits / max(len(blocks), 1), 4),
        "semantic_exclusion_ratio": round(semantic_hits / max(len(blocks), 1), 4),
        "authorish_ratio": round(author_hits / max(len(blocks), 1), 4),
        "contactish_ratio": round(contact_hits / max(len(blocks), 1), 4),
        "sentence_like_ratio": round(sentence_hits / max(len(blocks), 1), 4),
        "centeredness_mean": round(mean_centered, 4),
        "doc_y_mean": None if mean_doc_y is None else round(mean_doc_y, 4),
        "page_y_mean": None if mean_page_y is None else round(mean_page_y, 4),
        "dominant_role": role_counts.most_common(1)[0][0] if role_counts else None,
        "style_role": style_role,
    }


def build_document_model(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    styles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    style_counter: Counter[str] = Counter()

    for block in blocks:
        row = dict(block)
        row["style_key"] = style_key(row)
        annotated.append(row)
        styles[row["style_key"]].append(row)
        style_counter[row["style_key"]] += 1

    body_counter: Counter[str] = Counter()
    for row in annotated:
        if is_body_like(row):
            body_counter[row["style_key"]] += 1

    if body_counter:
        body_style_key, _ = body_counter.most_common(1)[0]
    elif style_counter:
        body_style_key, _ = style_counter.most_common(1)[0]
    else:
        body_style_key = "unknown|0.0|b0|i0"

    body_blocks = styles.get(body_style_key, [])
    body_font_size = max((_safe_float(b.get("font_size")) for b in body_blocks), default=0.0)
    body_font_family = None
    if body_blocks:
        body_font_family = (
            body_blocks[0].get("font_family_normalized")
            or body_blocks[0].get("font_family")
            or body_blocks[0].get("font_name")
        )

    max_font_size = max((_safe_float(b.get("font_size")) for b in annotated), default=0.0)

    style_clusters: list[dict[str, Any]] = []
    heading_style_candidates: list[str] = []
    title_style_keys: list[str] = []
    furniture_style_keys: list[str] = []
    author_style_keys: list[str] = []
    contact_style_keys: list[str] = []

    for style, cluster_blocks in styles.items():
        summary = _cluster_summary(style, cluster_blocks, body_style_key, max_font_size)
        style_clusters.append(summary)

        if summary["style_role"] == "heading_candidate":
            heading_style_candidates.append(style)
        elif summary["style_role"] == "title_candidate":
            title_style_keys.append(style)
        elif summary["style_role"] == "furniture":
            furniture_style_keys.append(style)
        elif summary["style_role"] == "author_candidate":
            author_style_keys.append(style)
        elif summary["style_role"] == "contact_candidate":
            contact_style_keys.append(style)

    def _style_font_size(style: str) -> float:
        cluster = next((c for c in style_clusters if c["style_key"] == style), None)
        return _safe_float(cluster.get("font_size")) if cluster else 0.0

    heading_style_candidates = sorted(
        set(heading_style_candidates),
        key=lambda s: (-_style_font_size(s), s),
    )

    heading_level_by_style: dict[str, int] = {}
    for idx, style in enumerate(heading_style_candidates, start=1):
        heading_level_by_style[style] = idx

    body_entry_block_index = None
    for row in annotated:
        if is_body_like(row):
            body_entry_block_index = _safe_int(row.get("block_index"))
            break

    title_block_limit = None
    titleish_indices = []
    for row in annotated:
        s_key = row["style_key"]
        if s_key in title_style_keys or looks_authorish(row):
            titleish_indices.append(_safe_int(row.get("block_index")))
    if titleish_indices:
        title_block_limit = max(titleish_indices)

    exclusion_summary = {
        "page_furniture_blocks": sum(1 for row in annotated if is_page_furniture(row)),
        "semantic_exclusion_blocks": sum(1 for row in annotated if is_semantic_exclusion(row)),
        "authorish_blocks": sum(1 for row in annotated if looks_authorish(row)),
        "contactish_blocks": sum(1 for row in annotated if looks_contactish(row)),
    }

    return {
        "body_style_key": body_style_key,
        "body_font_family": body_font_family,
        "body_font_size": round(body_font_size, 1) if body_font_size else None,
        "style_clusters": style_clusters,
        "heading_style_candidates": heading_style_candidates,
        "heading_level_by_style": heading_level_by_style,
        "title_style_keys": title_style_keys,
        "furniture_style_keys": furniture_style_keys,
        "author_style_keys": author_style_keys,
        "contact_style_keys": contact_style_keys,
        "body_entry_block_index": body_entry_block_index,
        "title_block_limit": title_block_limit,
        "max_font_size": round(max_font_size, 1) if max_font_size else None,
        "exclusion_summary": exclusion_summary,
    }
