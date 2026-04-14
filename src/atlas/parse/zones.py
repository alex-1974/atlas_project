from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from statistics import median

from atlas.parse.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class FurnitureBand:
    side: str  # "top" | "bottom"
    y0: float
    y1: float
    coverage_ratio: float
    pages_present: int
    page_parity: str = "all"  # "all" | "odd" | "even"

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MarginZone:
    side: str  # "left" | "right"
    x0: float
    x1: float
    coverage_ratio: float
    pages_present: int

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class BodyRegion:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageFurnitureCandidate:
    side: str
    y0: float
    y1: float
    y0_rel: float
    y1_rel: float
    width_rel: float
    height_rel: float
    gap_rel: float
    body_gap_rel: float
    score: float
    block_count: int
    total_box_count: int
    left_count: int
    center_count: int
    right_count: int
    page_number_like_count: int
    slot_pattern: str

    def to_dict(self) -> dict:
        return asdict(self)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _group_by_page(blocks: list[object]) -> dict[int, list[object]]:
    pages: dict[int, list[object]] = {}
    for block in blocks:
        pages.setdefault(block.page_index, []).append(block)
    return pages


def _is_text_like(block: object) -> bool:
    return getattr(block, "block_type", None) == 0 and bool(
        str(getattr(block, "text", "")).strip()
    )


def _is_odd_page(page_index: int) -> bool:
    return (page_index + 1) % 2 == 1


def _merge_x_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []

    intervals = sorted(intervals, key=lambda it: it[0])
    merged: list[list[float]] = [[intervals[0][0], intervals[0][1]]]

    for x0, x1 in intervals[1:]:
        if x0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])

    return [(x0, x1) for x0, x1 in merged]


def _interval_coverage(intervals: list[tuple[float, float]], page_width: float) -> float:
    if not intervals or page_width <= 0:
        return 0.0
    covered = sum(max(0.0, x1 - x0) for x0, x1 in intervals)
    return covered / page_width


def classify_document_length(page_count: int) -> str:
    if page_count < 8:
        return "very_short"
    if page_count < 16:
        return "short"
    if page_count < 40:
        return "medium"
    return "long"


def _document_class_params(page_count: int) -> dict[str, float | int | bool]:
    length_class = classify_document_length(page_count)

    if length_class == "very_short":
        return {
            "length_class": length_class,
            "edge_ratio": 0.25,
            "min_cluster_pages": 0,
            "allow_global_model": False,
            "y_tol_rel": 0.020,
            "h_tol_rel": 0.025,
            "header_match_tol_rel": 0.025,
            "footer_match_tol_rel": 0.030,
            "header_global_threshold": 0.85,
            "footer_global_threshold": 0.75,
            "min_local_score_header": 0.22,
            "min_local_score_footer": 0.14,
            "match_tol_rel": 0.03,
            "header_max_y0_rel": 0.15,
            "header_max_height_rel": 0.05,
            "body_gap_min_rel": 0.005,
            "global_quality_threshold": 0.85,
        }

    if length_class == "short":
        return {
            "length_class": length_class,
            "edge_ratio": 0.25,
            "min_cluster_pages": 2,
            "allow_global_model": True,
            "y_tol_rel": 0.018,
            "h_tol_rel": 0.022,
            "header_match_tol_rel": 0.022,
            "footer_match_tol_rel": 0.028,
            "header_global_threshold": 0.85,
            "footer_global_threshold": 0.75,
            "min_local_score_header": 0.26,
            "min_local_score_footer": 0.16,
            "match_tol_rel": 0.025,
            "header_max_y0_rel": 0.13,
            "header_max_height_rel": 0.045,
            "body_gap_min_rel": 0.008,
            "global_quality_threshold": 0.85,
        }

    if length_class == "medium":
        return {
            "length_class": length_class,
            "edge_ratio": 0.25,
            "min_cluster_pages": 3,
            "allow_global_model": True,
            "y_tol_rel": 0.015,
            "h_tol_rel": 0.020,
            "header_match_tol_rel": 0.020,
            "footer_match_tol_rel": 0.026,
            "header_global_threshold": 0.82,
            "footer_global_threshold": 0.75,
            "min_local_score_header": 0.30,
            "min_local_score_footer": 0.18,
            "match_tol_rel": 0.02,
            "header_max_y0_rel": 0.12,
            "header_max_height_rel": 0.04,
            "body_gap_min_rel": 0.01,
            "global_quality_threshold": 0.82,
        }

    return {
            "length_class": length_class,
            "edge_ratio": 0.25,
            "min_cluster_pages": 4,
            "allow_global_model": True,
            "y_tol_rel": 0.012,
            "h_tol_rel": 0.018,
            "header_match_tol_rel": 0.018,
            "footer_match_tol_rel": 0.025,
            "header_global_threshold": 0.80,
            "footer_global_threshold": 0.75,
            "min_local_score_header": 0.32,
            "min_local_score_footer": 0.20,
            "match_tol_rel": 0.02,
            "header_max_y0_rel": 0.12,
            "header_max_height_rel": 0.04,
            "body_gap_min_rel": 0.01,
            "global_quality_threshold": 0.80,
        }


def _middle_page_indexes(page_count: int) -> list[int]:
    if page_count <= 6:
        return list(range(page_count))

    start = max(0, int(page_count / 3))
    end = min(page_count, int(2 * page_count / 3))

    if end <= start:
        return list(range(page_count))

    return list(range(start, end))


def _y_overlap(a: tuple[float, float], b: tuple[float, float], tol: float = 2.0) -> bool:
    ay0, ay1 = a
    by0, by1 = b
    return max(ay0, by0) <= min(ay1, by1) + tol


def _norm_y(y: float, page_height: float) -> float:
    if page_height <= 0:
        return 0.0
    return y / page_height


def _looks_like_page_number(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    t = t.replace("–", "-").replace("—", "-").strip()
    if re.fullmatch(r"\d{1,4}", t):
        return True
    if re.fullmatch(r"\[\d{1,4}\]", t):
        return True
    if re.fullmatch(r"[ivxlcdmIVXLCDM]{1,10}", t):
        return True
    return False


def _slot_for_box(x0: float, x1: float, page_width: float) -> str:
    if page_width <= 0:
        return "C"
    xc = (x0 + x1) / 2.0
    rel = xc / page_width
    if rel < 1.0 / 3.0:
        return "L"
    if rel < 2.0 / 3.0:
        return "C"
    return "R"


def _slot_pattern_from_blocks(blocks: list[object], page_width: float) -> tuple[str, int, int, int, int]:
    left_count = 0
    center_count = 0
    right_count = 0
    page_number_like_count = 0
    seen_slots: list[str] = []

    for block in blocks:
        slot = _slot_for_box(float(block.x0), float(block.x1), page_width)
        if slot == "L":
            left_count += 1
        elif slot == "C":
            center_count += 1
        else:
            right_count += 1

        if slot not in seen_slots:
            seen_slots.append(slot)

        text = str(getattr(block, "text", "")).strip()
        if _looks_like_page_number(text):
            page_number_like_count += 1

    parts: list[str] = []
    if left_count > 0:
        parts.append("L")
    if center_count > 0:
        parts.append("C")
    if right_count > 0:
        parts.append("R")

    pattern = "+".join(parts) if parts else "none"
    return pattern, left_count, center_count, right_count, page_number_like_count


def _build_horizontal_band_groups(
    page_blocks: list[object],
    *,
    page_height: float,
    band_merge_tol_abs: float = 2.0,
    max_band_height_ratio: float = 0.18,
) -> list[dict[str, object]]:
    text_blocks = [b for b in page_blocks if _is_text_like(b)]
    if not text_blocks:
        return []

    sorted_blocks = sorted(text_blocks, key=lambda b: (float(b.y0), float(b.x0)))
    groups: list[list[object]] = []

    for block in sorted_blocks:
        interval = (float(block.y0), float(block.y1))
        attached = False

        for group in groups:
            gy0 = min(float(b.y0) for b in group)
            gy1 = max(float(b.y1) for b in group)
            if _y_overlap(interval, (gy0, gy1), tol=band_merge_tol_abs):
                group.append(block)
                attached = True
                break

        if not attached:
            groups.append([block])

    band_groups: list[dict[str, object]] = []

    for group in groups:
        x0 = min(float(b.x0) for b in group)
        x1 = max(float(b.x1) for b in group)
        y0 = min(float(b.y0) for b in group)
        y1 = max(float(b.y1) for b in group)

        if x1 <= x0 or y1 <= y0:
            continue
        if (y1 - y0) > page_height * max_band_height_ratio:
            continue

        band_groups.append(
            {
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "blocks": group,
            }
        )

    band_groups.sort(key=lambda item: (float(item["y0"]), float(item["x0"])))
    return band_groups


def _build_horizontal_bands_from_blocks(
    page_blocks: list[object],
    *,
    page_height: float,
    band_merge_tol_abs: float = 2.0,
    max_band_height_ratio: float = 0.18,
) -> list[tuple[float, float, float, float, int]]:
    groups = _build_horizontal_band_groups(
        page_blocks,
        page_height=page_height,
        band_merge_tol_abs=band_merge_tol_abs,
        max_band_height_ratio=max_band_height_ratio,
    )
    return [
        (
            float(g["x0"]),
            float(g["y0"]),
            float(g["x1"]),
            float(g["y1"]),
            len(g["blocks"]),
        )
        for g in groups
    ]


def _candidate_region_blocks(
    page_blocks: list[object],
    *,
    page_height: float,
    side: str,
    edge_ratio: float,
) -> list[object]:
    if side == "top":
        limit = page_height * edge_ratio
        return [b for b in page_blocks if _is_text_like(b) and float(b.y0) <= limit]

    limit = page_height * (1.0 - edge_ratio)
    return [b for b in page_blocks if _is_text_like(b) and float(b.y1) >= limit]


def _header_structure_score(
    *,
    slot_pattern: str,
    total_box_count: int,
    page_number_like_count: int,
) -> float:
    score = 0.0

    if slot_pattern in {"L+R", "C", "L", "R", "L+C", "C+R", "L+C+R"}:
        score += 0.20

    if total_box_count in {1, 2, 3}:
        score += 0.15
    elif total_box_count <= 5:
        score += 0.05
    else:
        score -= 0.10

    if page_number_like_count > 0:
        score += 0.05

    return score


def _footer_structure_score(
    *,
    slot_pattern: str,
    total_box_count: int,
    page_number_like_count: int,
    width_rel: float,
    height_rel: float,
) -> float:
    score = 0.0

    if slot_pattern in {"L", "R", "C"}:
        score += 0.55
    elif slot_pattern in {"L+R", "L+C", "C+R", "L+C+R"}:
        score += 0.20

    if total_box_count == 1:
        score += 0.30
    elif total_box_count == 2:
        score += 0.18
    elif total_box_count == 3:
        score += 0.08
    else:
        score -= 0.20

    if page_number_like_count > 0:
        score += 0.40

    if width_rel < 0.08:
        score += 0.20
    elif width_rel < 0.20:
        score += 0.14
    elif width_rel < 0.45:
        score += 0.04
    elif width_rel > 0.70:
        score -= 0.25

    if height_rel > 0.06:
        score -= 0.20

    return score


def _body_gap_rel_for_band(
    band_groups: list[dict[str, object]],
    idx: int,
    side: str,
    page_height: float,
) -> float:
    if side == "top":
        if idx + 1 >= len(band_groups):
            return 0.0
        gap = max(0.0, float(band_groups[idx + 1]["y0"]) - float(band_groups[idx]["y1"]))
        return _norm_y(gap, page_height)

    if idx - 1 < 0:
        return 0.0
    gap = max(0.0, float(band_groups[idx]["y0"]) - float(band_groups[idx - 1]["y1"]))
    return _norm_y(gap, page_height)


def _build_band_candidates_with_gaps(
    page_blocks: list[object],
    *,
    page_width: float,
    page_height: float,
    side: str,
    edge_ratio: float,
) -> list[PageFurnitureCandidate]:
    edge_blocks = _candidate_region_blocks(
        page_blocks,
        page_height=page_height,
        side=side,
        edge_ratio=edge_ratio,
    )
    if not edge_blocks:
        return []

    band_groups = _build_horizontal_band_groups(edge_blocks, page_height=page_height)
    if not band_groups:
        return []

    candidates: list[PageFurnitureCandidate] = []

    for idx, group in enumerate(band_groups):
        x0 = float(group["x0"])
        x1 = float(group["x1"])
        y0 = float(group["y0"])
        y1 = float(group["y1"])
        band_blocks = list(group["blocks"])

        y0_rel = _norm_y(y0, page_height)
        y1_rel = _norm_y(y1, page_height)
        width_rel = (x1 - x0) / page_width if page_width > 0 else 0.0
        height_rel = y1_rel - y0_rel
        body_gap_rel = _body_gap_rel_for_band(band_groups, idx, side, page_height)

        slot_pattern, left_count, center_count, right_count, page_number_like_count = (
            _slot_pattern_from_blocks(band_blocks, page_width)
        )
        total_box_count = len(band_blocks)

        if side == "top":
            if idx != 0:
                continue
            if y1_rel > edge_ratio:
                continue

            next_gap = 0.0
            if idx + 1 < len(band_groups):
                next_gap = max(0.0, float(band_groups[idx + 1]["y0"]) - y1)
            gap_rel = _norm_y(next_gap, page_height)

            structure_score = max(
                0.0,
                min(
                    1.0,
                    _header_structure_score(
                        slot_pattern=slot_pattern,
                        total_box_count=total_box_count,
                        page_number_like_count=page_number_like_count,
                    ),
                ),
            )

            score = (
                0.34 * gap_rel
                + 0.34 * body_gap_rel
                + 0.14 * (1.0 - min(height_rel / 0.08, 1.0))
                + 0.10 * (1.0 if y0_rel <= 0.10 else max(0.0, 1.0 - (y0_rel - 0.10) / 0.10))
                + 0.08 * structure_score
            )
        else:
            if idx != len(band_groups) - 1:
                continue
            if y0_rel < 1.0 - edge_ratio:
                continue

            prev_gap = 0.0
            if idx - 1 >= 0:
                prev_gap = max(0.0, y0 - float(band_groups[idx - 1]["y1"]))
            gap_rel = _norm_y(prev_gap, page_height)

            depth_score = max(0.0, min(1.0, (y1_rel - 0.82) / 0.18))
            compact_score = 1.0 - min(height_rel / 0.06, 1.0)
            structure_score = max(
                0.0,
                min(
                    1.0,
                    _footer_structure_score(
                        slot_pattern=slot_pattern,
                        total_box_count=total_box_count,
                        page_number_like_count=page_number_like_count,
                        width_rel=width_rel,
                        height_rel=height_rel,
                    ),
                ),
            )

            score = (
                0.24 * depth_score
                + 0.18 * compact_score
                + 0.18 * gap_rel
                + 0.18 * body_gap_rel
                + 0.22 * structure_score
            )

        logger.debug(
            "candidate side=%s y0=%.2f y1=%.2f "
            "y0_rel=%.4f y1_rel=%.4f height_rel=%.4f width_rel=%.4f "
            "gap_rel=%.4f body_gap_rel=%.4f boxes=%d slot=%s "
            "L=%d C=%d R=%d page_num_like=%d score=%.4f",
            side,
            y0,
            y1,
            y0_rel,
            y1_rel,
            height_rel,
            width_rel,
            gap_rel,
            body_gap_rel,
            total_box_count,
            slot_pattern,
            left_count,
            center_count,
            right_count,
            page_number_like_count,
            score,
        )

        candidates.append(
            PageFurnitureCandidate(
                side=side,
                y0=y0,
                y1=y1,
                y0_rel=y0_rel,
                y1_rel=y1_rel,
                width_rel=width_rel,
                height_rel=height_rel,
                gap_rel=gap_rel,
                body_gap_rel=body_gap_rel,
                score=score,
                block_count=total_box_count,
                total_box_count=total_box_count,
                left_count=left_count,
                center_count=center_count,
                right_count=right_count,
                page_number_like_count=page_number_like_count,
                slot_pattern=slot_pattern,
            )
        )

    return candidates


def _select_page_edge_candidates(
    page_blocks: list[object],
    *,
    page_width: float,
    page_height: float,
    side: str,
    edge_ratio: float,
) -> list[tuple[float, float, float]]:
    candidates = _build_band_candidates_with_gaps(
        page_blocks,
        page_width=page_width,
        page_height=page_height,
        side=side,
        edge_ratio=edge_ratio,
    )
    return [(c.y0_rel, c.y1_rel, c.width_rel) for c in candidates]


def _best_page_candidate(
    page_blocks: list[object],
    *,
    page_width: float,
    page_height: float,
    side: str,
    page_count: int,
) -> PageFurnitureCandidate | None:
    params = _document_class_params(page_count)
    candidates = _build_band_candidates_with_gaps(
        page_blocks,
        page_width=page_width,
        page_height=page_height,
        side=side,
        edge_ratio=float(params["edge_ratio"]),
    )
    if not candidates:
        logger.debug("best_candidate side=%s none", side)
        return None

    best = max(candidates, key=lambda c: c.score)
    logger.debug(
        "best_candidate side=%s y0=%.2f y1=%.2f "
        "slot=%s boxes=%d score=%.4f body_gap_rel=%.4f",
        side,
        best.y0,
        best.y1,
        best.slot_pattern,
        best.total_box_count,
        best.score,
        best.body_gap_rel,
    )
    return best


def _build_horizontal_band_candidate(
    page_blocks: list[object],
    page_width: float,
    page_height: float,
    side: str,
) -> tuple[float, float, float] | None:
    candidate = _best_page_candidate(
        page_blocks,
        page_width=page_width,
        page_height=page_height,
        side=side,
        page_count=20,
    )
    if candidate is None:
        return None
    return (candidate.y0, candidate.y1, candidate.width_rel)


def _page_band_candidates(
    page_map: dict[int, list[object]],
    page_width: float,
    page_height: float,
    side: str,
    page_count: int,
    eligible_pages: list[int] | None = None,
) -> dict[int, list[tuple[float, float, float]]]:
    params = _document_class_params(page_count)
    result: dict[int, list[tuple[float, float, float]]] = {}
    pages = eligible_pages if eligible_pages is not None else sorted(page_map.keys())

    for page_index in pages:
        page_blocks = page_map.get(page_index, [])
        candidates = _select_page_edge_candidates(
            page_blocks,
            page_width=page_width,
            page_height=page_height,
            side=side,
            edge_ratio=float(params["edge_ratio"]),
        )
        if candidates:
            result[page_index] = candidates

    return result


def _cluster_band_candidates(
    candidates: list[tuple[int, tuple[float, float, float]]],
    *,
    y_tol_rel: float,
    h_tol_rel: float,
) -> list[dict[str, object]]:
    if not candidates:
        return []

    clusters: list[dict[str, object]] = []

    for page_index, (y0_rel, y1_rel, width_rel) in candidates:
        h_rel = y1_rel - y0_rel
        assigned = False

        for cluster in clusters:
            cy0 = cluster["y0_med"]
            cy1 = cluster["y1_med"]
            ch = cluster["h_med"]

            if (
                abs(y0_rel - cy0) <= y_tol_rel
                and abs(y1_rel - cy1) <= y_tol_rel
                and abs(h_rel - ch) <= h_tol_rel
            ):
                cluster["members"].append((page_index, y0_rel, y1_rel, width_rel))
                vals_y0 = [m[1] for m in cluster["members"]]
                vals_y1 = [m[2] for m in cluster["members"]]
                vals_h = [m[2] - m[1] for m in cluster["members"]]
                cluster["y0_med"] = _median(vals_y0)
                cluster["y1_med"] = _median(vals_y1)
                cluster["h_med"] = _median(vals_h)
                assigned = True
                break

        if not assigned:
            clusters.append(
                {
                    "members": [(page_index, y0_rel, y1_rel, width_rel)],
                    "y0_med": y0_rel,
                    "y1_med": y1_rel,
                    "h_med": h_rel,
                }
            )

    return clusters


def _min_pages_required(eligible_page_count: int, configured_min_cluster_pages: int) -> int:
    if configured_min_cluster_pages <= 0:
        return 1
    if eligible_page_count <= 3:
        return min(2, max(1, eligible_page_count))
    if eligible_page_count <= 6:
        return min(configured_min_cluster_pages, 2)
    return configured_min_cluster_pages


def _score_cluster(
    cluster: dict[str, object],
    *,
    eligible_page_count: int,
    side: str,
    min_cluster_pages: int,
) -> float:
    members = cluster["members"]
    pages_present = len({m[0] for m in members})

    min_pages = _min_pages_required(eligible_page_count, min_cluster_pages)
    if pages_present < min_pages:
        return -1e9

    coverage_ratio = pages_present / max(1, eligible_page_count)
    y0_values = [m[1] for m in members]
    y1_values = [m[2] for m in members]
    h_values = [m[2] - m[1] for m in members]
    mean_width = sum(m[3] for m in members) / max(1, len(members))

    y0_med = cluster["y0_med"]
    y1_med = cluster["y1_med"]
    h_med = cluster["h_med"]

    y0_spread = max(y0_values) - min(y0_values) if y0_values else 0.0
    y1_spread = max(y1_values) - min(y1_values) if y1_values else 0.0
    h_spread = max(h_values) - min(h_values) if h_values else 0.0
    stability_penalty = y0_spread + y1_spread + h_spread

    # Harte Plausibilitätsgrenzen
    if side == "top":
        if y0_med > 0.13:
            return -1e9
        if y1_med > 0.20:
            return -1e9
        if h_med > 0.09:
            return -1e9

        # Header müssen global deutlich stabiler sein
        if eligible_page_count >= 10 and coverage_ratio < 0.30:
            return -1e9
        if eligible_page_count >= 25 and coverage_ratio < 0.35:
            return -1e9
        if stability_penalty > 0.035:
            return -1e9

        # Header: Stabilität und Coverage stark priorisieren
        return (
            12.0 * coverage_ratio
            - 16.0 * stability_penalty
            - 3.0 * h_med
            + 0.05 * mean_width
        )

    # Footer: bestehende Logik weitgehend beibehalten
    if y1_med < 0.80:
        return -1e9
    if y0_med < 0.68:
        return -1e9
    if h_med > 0.12:
        return -1e9

    return 8.0 * coverage_ratio + 0.12 * mean_width - 8.0 * stability_penalty


def _cluster_to_band(
    cluster: dict[str, object],
    *,
    side: str,
    page_parity: str,
    eligible_page_count: int,
    page_height: float,
    min_cluster_pages: int,
) -> FurnitureBand | None:
    members = cluster["members"]
    if not members:
        return None

    pages_present = len({m[0] for m in members})
    min_pages = _min_pages_required(eligible_page_count, min_cluster_pages)
    if pages_present < min_pages:
        return None

    y0_rel_values = [m[1] for m in members]
    y1_rel_values = [m[2] for m in members]

    y0_rel = _percentile(y0_rel_values, 0.20)
    y1_rel = _percentile(y1_rel_values, 0.80)

    if y1_rel <= y0_rel:
        return None

    return FurnitureBand(
        side=side,
        y0=y0_rel * page_height,
        y1=y1_rel * page_height,
        coverage_ratio=pages_present / max(1, eligible_page_count),
        pages_present=pages_present,
        page_parity=page_parity,
    )


def _band_quality(
    band: FurnitureBand | None,
    candidates_by_page: dict[int, list[tuple[float, float, float]]],
    page_indexes: list[int],
    *,
    side: str,
    page_height: float,
    y_match_tol_rel: float,
) -> float:
    if band is None or not page_indexes:
        return 0.0

    band_y0_rel = _norm_y(band.y0, page_height)
    band_y1_rel = _norm_y(band.y1, page_height)

    pages_with_any_candidate = 0
    pages_with_match = 0
    all_y0: list[float] = []
    all_y1: list[float] = []

    for page_index in page_indexes:
        page_candidates = candidates_by_page.get(page_index, [])
        if page_candidates:
            pages_with_any_candidate += 1

        matched_here = False
        for y0_rel, y1_rel, _width_rel in page_candidates:
            if (
                abs(y0_rel - band_y0_rel) <= y_match_tol_rel
                and abs(y1_rel - band_y1_rel) <= y_match_tol_rel
            ):
                matched_here = True
                all_y0.append(y0_rel)
                all_y1.append(y1_rel)

        if matched_here:
            pages_with_match += 1

    if pages_with_any_candidate == 0:
        return 0.0

    coverage = pages_with_match / max(1, len(page_indexes))
    match_rate = pages_with_match / max(1, pages_with_any_candidate)

    if all_y0 and all_y1:
        y0_spread = max(all_y0) - min(all_y0)
        y1_spread = max(all_y1) - min(all_y1)
        stability = max(0.0, 1.0 - 12.0 * (y0_spread + y1_spread))
    else:
        stability = 0.0

    if side == "top":
        plausibility = 1.0
        if band_y0_rel > 0.12:
            plausibility *= 0.5
        if band_y1_rel > 0.20:
            plausibility *= 0.5
        if band.height / page_height > 0.08:
            plausibility *= 0.7

        # Header-Qualität stärker global/stabilitätsgetrieben
        quality = (
            0.55 * coverage
            + 0.20 * match_rate
            + 0.20 * stability
            + 0.05 * plausibility
        )
        return _clamp(quality, 0.0, 1.0)

    plausibility = 1.0
    if band_y0_rel < 0.68:
        plausibility *= 0.5
    if band_y1_rel < 0.80:
        plausibility *= 0.5

    quality = 0.45 * coverage + 0.30 * match_rate + 0.15 * stability + 0.10 * plausibility
    return _clamp(quality, 0.0, 1.0)


def _quality_mode(quality: float) -> str:
    if quality >= 0.75:
        return "global"
    if quality >= 0.45:
        return "hybrid"
    return "local_fallback"


def _best_band_from_candidates(
    candidates_by_page: dict[int, list[tuple[float, float, float]]],
    page_indexes: list[int],
    *,
    side: str,
    page_parity: str,
    page_height: float,
    page_count: int,
) -> FurnitureBand | None:
    params = _document_class_params(page_count)
    if not bool(params["allow_global_model"]):
        return None

    if page_parity == "odd":
        eligible_pages = [p for p in page_indexes if _is_odd_page(p)]
    elif page_parity == "even":
        eligible_pages = [p for p in page_indexes if not _is_odd_page(p)]
    else:
        eligible_pages = list(page_indexes)

    if not eligible_pages:
        return None

    flat_candidates: list[tuple[int, tuple[float, float, float]]] = []
    for page_index in eligible_pages:
        for candidate in candidates_by_page.get(page_index, []):
            flat_candidates.append((page_index, candidate))

    if not flat_candidates:
        return None

    clusters = _cluster_band_candidates(
        flat_candidates,
        y_tol_rel=float(params["y_tol_rel"]),
        h_tol_rel=float(params["h_tol_rel"]),
    )
    if not clusters:
        return None

    best_cluster = max(
        clusters,
        key=lambda cluster: _score_cluster(
            cluster,
            eligible_page_count=len(eligible_pages),
            side=side,
            min_cluster_pages=int(params["min_cluster_pages"]),
        ),
    )

    if (
        _score_cluster(
            best_cluster,
            eligible_page_count=len(eligible_pages),
            side=side,
            min_cluster_pages=int(params["min_cluster_pages"]),
        )
        < 0
    ):
        return None

    return _cluster_to_band(
        best_cluster,
        side=side,
        page_parity=page_parity,
        eligible_page_count=len(eligible_pages),
        page_height=page_height,
        min_cluster_pages=int(params["min_cluster_pages"]),
    )


def _aggregate_band_candidates(
    candidates: dict[int, tuple[float, float, float]] | dict[int, list[tuple[float, float, float]]],
    page_indexes: list[int],
    side: str,
    page_parity: str,
    page_height: float,
) -> FurnitureBand | None:
    normalized: dict[int, list[tuple[float, float, float]]] = {}

    for page_index, value in candidates.items():
        values = [value] if isinstance(value, tuple) else value
        converted: list[tuple[float, float, float]] = []

        for y0, y1, third in values:
            if y0 > 1.0 or y1 > 1.0:
                if page_height <= 0:
                    continue
                converted.append((y0 / page_height, y1 / page_height, third))
            else:
                converted.append((y0, y1, third))

        if converted:
            normalized[page_index] = converted

    return _best_band_from_candidates(
        normalized,
        page_indexes,
        side=side,
        page_parity=page_parity,
        page_height=page_height,
        page_count=max(len(page_indexes), 20),
    )


def _merge_top_bands(bands: list[FurnitureBand | None]) -> FurnitureBand | None:
    valid = [b for b in bands if b is not None]
    if not valid:
        return None
    return FurnitureBand(
        side="top",
        y0=min(b.y0 for b in valid),
        y1=max(b.y1 for b in valid),
        coverage_ratio=max(b.coverage_ratio for b in valid),
        pages_present=max(b.pages_present for b in valid),
        page_parity="all",
    )


def _merge_bottom_bands(bands: list[FurnitureBand | None]) -> FurnitureBand | None:
    valid = [b for b in bands if b is not None]
    if not valid:
        return None
    return FurnitureBand(
        side="bottom",
        y0=min(b.y0 for b in valid),
        y1=max(b.y1 for b in valid),
        coverage_ratio=max(b.coverage_ratio for b in valid),
        pages_present=max(b.pages_present for b in valid),
        page_parity="all",
    )


def detect_repeated_furniture_bands(
    blocks: list[object],
    page_count: int,
    page_width: float,
    page_height: float,
) -> tuple[
    FurnitureBand | None,
    FurnitureBand | None,
    FurnitureBand | None,
    FurnitureBand | None,
    FurnitureBand | None,
    FurnitureBand | None,
    dict[str, object],
]:
    params = _document_class_params(page_count)
    text_blocks = [b for b in blocks if _is_text_like(b)]
    page_map = _group_by_page(text_blocks)
    middle_pages = _middle_page_indexes(page_count)

    top_candidates_middle = _page_band_candidates(
        page_map=page_map,
        page_width=page_width,
        page_height=page_height,
        side="top",
        page_count=page_count,
        eligible_pages=middle_pages,
    )
    bottom_candidates_middle = _page_band_candidates(
        page_map=page_map,
        page_width=page_width,
        page_height=page_height,
        side="bottom",
        page_count=page_count,
        eligible_pages=middle_pages,
    )

    header_all = _best_band_from_candidates(
        top_candidates_middle,
        middle_pages,
        side="top",
        page_parity="all",
        page_height=page_height,
        page_count=page_count,
    )
    header_odd = _best_band_from_candidates(
        top_candidates_middle,
        middle_pages,
        side="top",
        page_parity="odd",
        page_height=page_height,
        page_count=page_count,
    )
    header_even = _best_band_from_candidates(
        top_candidates_middle,
        middle_pages,
        side="top",
        page_parity="even",
        page_height=page_height,
        page_count=page_count,
    )

    footer_all = _best_band_from_candidates(
        bottom_candidates_middle,
        middle_pages,
        side="bottom",
        page_parity="all",
        page_height=page_height,
        page_count=page_count,
    )
    footer_odd = _best_band_from_candidates(
        bottom_candidates_middle,
        middle_pages,
        side="bottom",
        page_parity="odd",
        page_height=page_height,
        page_count=page_count,
    )
    footer_even = _best_band_from_candidates(
        bottom_candidates_middle,
        middle_pages,
        side="bottom",
        page_parity="even",
        page_height=page_height,
        page_count=page_count,
    )

    header_band = header_all or _merge_top_bands([header_odd, header_even])
    footer_band = footer_all or _merge_bottom_bands([footer_odd, footer_even])

    header_quality = _band_quality(
        header_band,
        top_candidates_middle,
        middle_pages,
        side="top",
        page_height=page_height,
        y_match_tol_rel=float(params["header_match_tol_rel"]),
    )
    footer_quality = _band_quality(
        footer_band,
        bottom_candidates_middle,
        middle_pages,
        side="bottom",
        page_height=page_height,
        y_match_tol_rel=float(params["footer_match_tol_rel"]),
    )

    logger.debug(
        "global_header band=%s quality=%.4f mode=%s middle_pages=%s",
        header_band.to_dict() if header_band else None,
        header_quality,
        _quality_mode(header_quality),
        [p + 1 for p in middle_pages],
    )
    logger.debug(
        "global_footer band=%s quality=%.4f mode=%s middle_pages=%s",
        footer_band.to_dict() if footer_band else None,
        footer_quality,
        _quality_mode(footer_quality),
        [p + 1 for p in middle_pages],
    )

    diagnostics = {
        "length_class": params["length_class"],
        "middle_pages": [p + 1 for p in middle_pages],
        "top_middle_candidates_count": sum(len(v) for v in top_candidates_middle.values()),
        "bottom_middle_candidates_count": sum(len(v) for v in bottom_candidates_middle.values()),
        "header_all": header_all.to_dict() if header_all else None,
        "header_odd": header_odd.to_dict() if header_odd else None,
        "header_even": header_even.to_dict() if header_even else None,
        "footer_all": footer_all.to_dict() if footer_all else None,
        "footer_odd": footer_odd.to_dict() if footer_odd else None,
        "footer_even": footer_even.to_dict() if footer_even else None,
        "header_quality": header_quality,
        "footer_quality": footer_quality,
        "header_mode": _quality_mode(header_quality),
        "footer_mode": _quality_mode(footer_quality),
    }

    return (
        header_band,
        footer_band,
        header_odd,
        header_even,
        footer_odd,
        footer_even,
        diagnostics,
    )


def decide_page_has_furniture(
    page_blocks: list[object],
    page_width: float,
    page_height: float,
    side: str,
    page_count: int,
    global_band: FurnitureBand | None = None,
    global_quality: float | None = None,
    body_region: BodyRegion | None = None,
) -> bool:
    params = _document_class_params(page_count)

    candidate = _best_page_candidate(
        page_blocks,
        page_width=page_width,
        page_height=page_height,
        side=side,
        page_count=page_count,
    )
    if candidate is None:
        logger.debug(
            "decision side=%s accepted=False reason=no_candidate global_quality=%s",
            side,
            f"{global_quality:.4f}" if global_quality is not None else None,
        )
        return False

    match_tol_rel = float(params["match_tol_rel"])
    header_max_y0_rel = float(params["header_max_y0_rel"])
    header_max_height_rel = float(params["header_max_height_rel"])
    body_gap_min_rel = float(params["body_gap_min_rel"])
    global_quality_threshold = float(params["global_quality_threshold"])

    min_local_score = (
        float(params["min_local_score_header"])
        if side == "top"
        else float(params["min_local_score_footer"])
    )

    header_global_threshold = float(params["header_global_threshold"])
    footer_global_threshold = float(params["footer_global_threshold"])

    # Zusätzliche Header-Filter gegen False Positives
    if side == "top":
        if candidate.y0_rel > header_max_y0_rel:
            logger.debug(
                "decision side=top accepted=False reason=header_too_low candidate_y0_rel=%.4f",
                candidate.y0_rel,
            )
            return False

        if candidate.height_rel > header_max_height_rel:
            logger.debug(
                "decision side=top accepted=False reason=header_too_tall candidate_height_rel=%.4f",
                candidate.height_rel,
            )
            return False

        effective_body_gap_rel = candidate.body_gap_rel
        if body_region is not None:
            effective_body_gap_rel = max(
                0.0,
                (float(body_region.y0) - candidate.y1) / page_height,
            )

        if effective_body_gap_rel < body_gap_min_rel:
            logger.debug(
                "decision side=top accepted=False reason=header_body_gap_too_small body_gap_rel=%.4f",
                effective_body_gap_rel,
            )
            return False

    if side == "bottom":
        if candidate.y1_rel < (1.0 - float(params["edge_ratio"])):
            logger.debug(
                "decision side=bottom accepted=False reason=footer_not_low_enough candidate_y1_rel=%.4f",
                candidate.y1_rel,
            )
            return False

    matches_global = False
    if global_band is not None:
        band_y0_rel = _norm_y(global_band.y0, page_height)
        band_y1_rel = _norm_y(global_band.y1, page_height)
        matches_global = (
            abs(candidate.y0_rel - band_y0_rel) <= match_tol_rel
            and abs(candidate.y1_rel - band_y1_rel) <= match_tol_rel
        )

    # --------------------------------------------------
    # HEADER: globales Muster stark priorisieren
    # --------------------------------------------------
    if side == "top":
        if global_band is not None and global_quality is not None:
            if global_quality >= header_global_threshold:
                logger.debug(
                    "decision side=top mode=global_strict accepted=%s "
                    "global_quality=%.4f matches_global=%s "
                    "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
                    matches_global,
                    global_quality,
                    matches_global,
                    candidate.score,
                    candidate.y0_rel,
                    candidate.y1_rel,
                    candidate.slot_pattern,
                    candidate.total_box_count,
                )
                return matches_global

            if global_quality >= 0.45:
                if matches_global:
                    logger.debug(
                        "decision side=top mode=global_soft accepted=True "
                        "global_quality=%.4f candidate_score=%.4f",
                        global_quality,
                        candidate.score,
                    )
                    return True

                # Nur bei sehr kurzen Dokumenten lokaler Header-Fallback
                if classify_document_length(page_count) in {"very_short", "short"}:
                    accepted = candidate.score >= min_local_score
                    logger.debug(
                        "decision side=top mode=local_short_doc accepted=%s "
                        "global_quality=%.4f matches_global=%s "
                        "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
                        accepted,
                        global_quality,
                        matches_global,
                        candidate.score,
                        candidate.y0_rel,
                        candidate.y1_rel,
                        candidate.slot_pattern,
                        candidate.total_box_count,
                    )
                    return accepted

                logger.debug(
                    "decision side=top mode=reject_nonmatching_global accepted=False "
                    "global_quality=%.4f matches_global=%s "
                    "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
                    global_quality,
                    matches_global,
                    candidate.score,
                    candidate.y0_rel,
                    candidate.y1_rel,
                    candidate.slot_pattern,
                    candidate.total_box_count,
                )
                return False

        # Kein globales Muster -> nur bei sehr kurzen Dokumenten lokale Heuristik
        if classify_document_length(page_count) in {"very_short", "short"}:
            accepted = candidate.score >= min_local_score
            logger.debug(
                "decision side=top mode=local_only_short accepted=%s "
                "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
                accepted,
                candidate.score,
                candidate.y0_rel,
                candidate.y1_rel,
                candidate.slot_pattern,
                candidate.total_box_count,
            )
            return accepted

        logger.debug(
            "decision side=top mode=no_global_reject accepted=False "
            "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
            candidate.score,
            candidate.y0_rel,
            candidate.y1_rel,
            candidate.slot_pattern,
            candidate.total_box_count,
        )
        return False

    # --------------------------------------------------
    # FOOTER: bestehende Logik beibehalten
    # --------------------------------------------------
    if global_band is not None and global_quality is not None:
        if global_quality >= footer_global_threshold:
            logger.debug(
                "decision side=bottom mode=global_strict accepted=%s "
                "global_quality=%.4f matches_global=%s "
                "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
                matches_global,
                global_quality,
                matches_global,
                candidate.score,
                candidate.y0_rel,
                candidate.y1_rel,
                candidate.slot_pattern,
                candidate.total_box_count,
            )
            return matches_global

        if matches_global:
            logger.debug(
                "decision side=bottom mode=global_soft accepted=True "
                "global_quality=%.4f candidate_score=%.4f",
                global_quality,
                candidate.score,
            )
            return True

    accepted = candidate.score >= min_local_score
    logger.debug(
        "decision side=bottom mode=local accepted=%s "
        "global_quality=%s matches_global=%s "
        "candidate_score=%.4f candidate=(%.4f, %.4f) slot=%s boxes=%d",
        accepted,
        f"{global_quality:.4f}" if global_quality is not None else None,
        matches_global,
        candidate.score,
        candidate.y0_rel,
        candidate.y1_rel,
        candidate.slot_pattern,
        candidate.total_box_count,
    )
    return accepted


def filter_out_furniture(
    blocks: list[object],
    header_band: FurnitureBand | None,
    footer_band: FurnitureBand | None,
) -> list[object]:
    result: list[object] = []

    for block in blocks:
        if not _is_text_like(block):
            continue
        if header_band and float(block.y1) <= header_band.y1 + 2.0:
            continue
        if footer_band and float(block.y0) >= footer_band.y0 - 2.0:
            continue
        result.append(block)

    return result


def detect_page_body_region(
    page_blocks: list[object],
    page_width: float,
    page_height: float,
) -> BodyRegion | None:
    text_blocks = [b for b in page_blocks if _is_text_like(b)]
    if not text_blocks:
        return None

    x0s = [float(b.x0) for b in text_blocks]
    x1s = [float(b.x1) for b in text_blocks]
    y0s = [float(b.y0) for b in text_blocks]
    y1s = [float(b.y1) for b in text_blocks]

    x0 = _clamp(_percentile(x0s, 0.15), 0.0, page_width)
    x1 = _clamp(_percentile(x1s, 0.85), 0.0, page_width)
    y0 = _clamp(_percentile(y0s, 0.15), 0.0, page_height)
    y1 = _clamp(_percentile(y1s, 0.85), 0.0, page_height)

    if x1 <= x0 or y1 <= y0:
        return None

    return BodyRegion(x0=x0, y0=y0, x1=x1, y1=y1)


def detect_page_body_regions(
    blocks: list[object],
    page_count: int,
    page_width: float,
    page_height: float,
) -> list[BodyRegion | None]:
    page_map = _group_by_page(blocks)
    regions: list[BodyRegion | None] = []

    for page_index in range(page_count):
        page_blocks = page_map.get(page_index, [])
        regions.append(detect_page_body_region(page_blocks, page_width, page_height))

    return regions


def detect_document_body_region_from_pages(
    page_regions: list[BodyRegion | None],
    page_width: float,
    page_height: float,
) -> BodyRegion | None:
    valid = [r for r in page_regions if r is not None]
    if not valid:
        return None

    x0 = _clamp(_percentile([r.x0 for r in valid], 0.15), 0.0, page_width)
    x1 = _clamp(_percentile([r.x1 for r in valid], 0.85), 0.0, page_width)
    y0 = _clamp(_percentile([r.y0 for r in valid], 0.15), 0.0, page_height)
    y1 = _clamp(_percentile([r.y1 for r in valid], 0.85), 0.0, page_height)

    if x1 <= x0 or y1 <= y0:
        return None

    return BodyRegion(x0=x0, y0=y0, x1=x1, y1=y1)


def detect_margin_zones(
    blocks: list[object],
    body: BodyRegion,
    page_count: int,
    page_width: float,
) -> tuple[MarginZone | None, MarginZone | None]:
    left_pages: set[int] = set()
    right_pages: set[int] = set()
    left_x0: list[float] = []
    left_x1: list[float] = []
    right_x0: list[float] = []
    right_x1: list[float] = []

    max_margin_width = page_width * 0.22

    for block in blocks:
        if not _is_text_like(block):
            continue

        bx0 = float(block.x0)
        bx1 = float(block.x1)

        if bx1 <= body.x0 and (bx1 - bx0) <= max_margin_width:
            left_pages.add(block.page_index)
            left_x0.append(bx0)
            left_x1.append(bx1)

        if bx0 >= body.x1 and (bx1 - bx0) <= max_margin_width:
            right_pages.add(block.page_index)
            right_x0.append(bx0)
            right_x1.append(bx1)

    left_zone = None
    if left_pages and len(left_pages) / max(1, page_count) >= 0.10:
        left_zone = MarginZone(
            side="left",
            x0=_percentile(left_x0, 0.10),
            x1=_percentile(left_x1, 0.90),
            coverage_ratio=len(left_pages) / page_count,
            pages_present=len(left_pages),
        )

    right_zone = None
    if right_pages and len(right_pages) / max(1, page_count) >= 0.10:
        right_zone = MarginZone(
            side="right",
            x0=_percentile(right_x0, 0.10),
            x1=_percentile(right_x1, 0.90),
            coverage_ratio=len(right_pages) / page_count,
            pages_present=len(right_pages),
        )

    return left_zone, right_zone


def refine_page_body_region(
    page_region: BodyRegion | None,
    page_blocks: list[object],
    left_margin_zone: MarginZone | None,
    right_margin_zone: MarginZone | None,
    page_width: float,
    page_height: float,
) -> BodyRegion | None:
    if page_region is None:
        return None

    usable: list[object] = []

    for block in page_blocks:
        if not _is_text_like(block):
            continue
        if left_margin_zone and float(block.x1) <= left_margin_zone.x1:
            continue
        if right_margin_zone and float(block.x0) >= right_margin_zone.x0:
            continue
        usable.append(block)

    if not usable:
        return page_region

    x0s = [float(b.x0) for b in usable]
    x1s = [float(b.x1) for b in usable]
    y0s = [float(b.y0) for b in usable]
    y1s = [float(b.y1) for b in usable]

    x0 = _clamp(_percentile(x0s, 0.15), 0.0, page_width)
    x1 = _clamp(_percentile(x1s, 0.85), 0.0, page_width)
    y0 = _clamp(_percentile(y0s, 0.15), 0.0, page_height)
    y1 = _clamp(_percentile(y1s, 0.85), 0.0, page_height)

    if x1 <= x0 or y1 <= y0:
        return page_region

    return BodyRegion(x0=x0, y0=y0, x1=x1, y1=y1)


def page_matches_band_candidate(
    page_blocks: list[object],
    page_width: float,
    page_height: float,
    side: str,
    band: FurnitureBand | None,
    tolerance_ratio: float = 0.02,
) -> bool:
    if band is None:
        return False

    candidate = _best_page_candidate(
        page_blocks,
        page_width=page_width,
        page_height=page_height,
        side=side,
        page_count=20,
    )
    if candidate is None:
        return False

    band_y0_rel = _norm_y(band.y0, page_height)
    band_y1_rel = _norm_y(band.y1, page_height)

    return (
        abs(candidate.y0_rel - band_y0_rel) <= tolerance_ratio
        and abs(candidate.y1_rel - band_y1_rel) <= tolerance_ratio
    )
