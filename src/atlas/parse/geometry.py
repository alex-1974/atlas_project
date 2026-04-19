from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
import math

import pymupdf as fitz  # PyMuPDF

from .zones import (
    BodyRegion,
    FurnitureBand,
    MarginZone,
    detect_document_body_region_from_pages,
    detect_margin_zones,
    detect_page_body_regions,
    detect_repeated_furniture_bands,
    refine_page_body_region,
    filter_out_furniture,
    page_matches_band_candidate,
    decide_page_has_furniture,
)

from .zones import (
    FurnitureMatch,
    FurnitureProfile,
    PageFurnitureObservation,
    filter_text_blocks_overlapping_images,
    infer_furniture_profile,
    match_page_to_furniture_profile,
)
from .vertical import (
    PageVerticalObservation,
    VerticalMatch,
    VerticalProfile,
    infer_vertical_profile,
    match_page_to_vertical_profile,
)


# -----------------------------------------------------------------------------
# Primitive layout objects
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class PageBlock:
    """
    Parsernahe Layout-Einheit auf Basis von PyMuPDF-Blocks.

    Koordinaten im MuPDF-Seitenraum:
    - Ursprung oben links
    - x wächst nach rechts
    - y wächst nach unten
    """

    page_index: int
    block_index: int
    block_type: int  # 0=text, 1=image
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def x_center(self) -> float:
        return self.x0 + self.width / 2.0

    @property
    def y_center(self) -> float:
        return self.y0 + self.height / 2.0

    @property
    def text_length(self) -> int:
        return len(self.text.strip())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ColumnBox:
    """
    Seitenlokale, spaltenkompatible Box auf Basis einzelner Textzeilen.
    """

    page_index: int
    parity: str  # "odd" | "even"
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


# -----------------------------------------------------------------------------
# Geometry model
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class ColumnLane:
    """
    Dokumentweit dominante vertikale Textbahn.
    """

    index: int
    x0: float
    x1: float
    pages_present: int
    coverage_ratio: float
    block_count: int

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RobustStats:
    median: float
    mad: float
    robust_sigma: float
    standard_error: float
    ci95_low: float
    ci95_high: float
    sample_size: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageColumnHypothesis:
    """
    Seitenweise Hypothese über die Zahl und Lage von Spalten.
    """

    page_index: int
    column_count: int
    lane_ranges_rel: list[tuple[float, float]]
    score: float
    candidate_line_count: int = 0
    wide_line_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageLayoutSignature:
    page_index: int
    page_number: int
    parity: str

    has_header: bool
    has_footer: bool

    body_x0: float | None
    body_x1: float | None
    body_y0: float | None
    body_y1: float | None

    page_column_count: int
    active_lane_indices: list[int]
    active_lane_ranges: list[tuple[float, float]]

    text_block_count: int
    column_box_count: int
    body_block_count: int

    def layout_key(self, x_step: float = 24.0, y_step: float = 36.0) -> str:
        def q(value: float | None, step: float) -> str:
            if value is None:
                return "na"
            return str(int(round(value / step) * step))

        body_present = int(
            self.body_x0 is not None
            and self.body_x1 is not None
            and self.body_y0 is not None
            and self.body_y1 is not None
        )

        width = (
            (self.body_x1 - self.body_x0)
            if self.body_x0 is not None and self.body_x1 is not None
            else None
        )
        height = (
            (self.body_y1 - self.body_y0)
            if self.body_y0 is not None and self.body_y1 is not None
            else None
        )

        return (
            f"body:{body_present}"
            f"|cols:{self.page_column_count}"
            f"|hdr:{int(self.has_header)}"
            f"|ftr:{int(self.has_footer)}"
            f"|bx0:{q(self.body_x0, x_step)}"
            f"|by0:{q(self.body_y0, y_step)}"
            f"|bw:{q(width, x_step)}"
            f"|bh:{q(height, y_step)}"
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["layout_key"] = self.layout_key()
        return data


@dataclass(slots=True)
class LayoutPattern:
    key: str
    pages_present: int
    total_pages: int
    coverage_ratio: float
    page_indexes: list[int]
    page_runs: list[tuple[int, int]]

    body_x0_stats: RobustStats | None = None
    body_x1_stats: RobustStats | None = None
    body_y0_stats: RobustStats | None = None
    body_y1_stats: RobustStats | None = None

    column_count_median: float | None = None
    column_count_mad: float | None = None

    stability_score: float | None = None
    confidence_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class GeometryProfile:
    page_count: int
    paper_width: float
    paper_height: float

    text_left: float
    text_right: float
    text_top: float
    text_bottom: float

    header_bottom: float
    footer_top: float

    margin_left: float
    margin_right: float

    column_count: int
    column_widths: list[float]
    column_gap: float | None
    column_lanes: list[ColumnLane] = field(default_factory=list)

    header_band: FurnitureBand | None = None
    footer_band: FurnitureBand | None = None
    header_band_odd: FurnitureBand | None = None
    header_band_even: FurnitureBand | None = None
    footer_band_odd: FurnitureBand | None = None
    footer_band_even: FurnitureBand | None = None

    left_margin_zone: MarginZone | None = None
    right_margin_zone: MarginZone | None = None

    body_region: BodyRegion | None = None
    page_body_regions: list[BodyRegion | None] = field(default_factory=list)

    page_layout_signatures: list[PageLayoutSignature] = field(default_factory=list)
    layout_patterns: list[LayoutPattern] = field(default_factory=list)

    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------


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


def _mad(values: list[float], med: float | None = None) -> float:
    if not values:
        return 0.0
    m = med if med is not None else _median(values)
    return _median([abs(v - m) for v in values])


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _group_by_page(blocks: list[PageBlock]) -> dict[int, list[PageBlock]]:
    pages: dict[int, list[PageBlock]] = {}
    for block in blocks:
        pages.setdefault(block.page_index, []).append(block)
    return pages


def _is_text_like(block: PageBlock) -> bool:
    return block.block_type == 0 and bool(block.text.strip())


def _is_odd_page(page_index: int) -> bool:
    return (page_index + 1) % 2 == 1


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _page_runs(page_indexes: list[int]) -> list[tuple[int, int]]:
    if not page_indexes:
        return []

    pages = sorted(page_indexes)
    runs: list[tuple[int, int]] = []
    start = pages[0]
    prev = pages[0]

    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append((start + 1, prev + 1))
        start = p
        prev = p

    runs.append((start + 1, prev + 1))
    return runs


def _robust_stats(values: list[float]) -> RobustStats | None:
    if not values:
        return None

    med = _median(values)
    mad = _mad(values, med)
    robust_sigma = 1.4826 * mad
    n = len(values)
    se = robust_sigma / math.sqrt(n) if n > 0 else 0.0
    ci_half = 1.96 * se

    return RobustStats(
        median=med,
        mad=mad,
        robust_sigma=robust_sigma,
        standard_error=se,
        ci95_low=med - ci_half,
        ci95_high=med + ci_half,
        sample_size=n,
    )


@dataclass(slots=True)
class PageFormatInfo:
    page_index: int
    width: float
    height: float
    orientation: str
    image_rects: list[tuple[float, float, float, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageFormatProfile:
    canonical_width: float
    canonical_height: float
    canonical_orientation: str
    profile_page_indexes: list[int]

    def to_dict(self) -> dict:
        return asdict(self)


def extract_page_formats(pdf_path: Path) -> list[PageFormatInfo]:
    page_formats: list[PageFormatInfo] = []
    with fitz.open(pdf_path) as doc:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            width = float(page.rect.width)
            height = float(page.rect.height)
            orientation = "landscape" if width > height else "portrait"
            image_rects: list[tuple[float, float, float, float]] = []
            for info in page.get_image_info(xrefs=True):
                bbox = info.get("bbox")
                if not bbox:
                    continue
                try:
                    x0, y0, x1, y1 = map(float, bbox)
                except Exception:
                    continue
                if x1 <= x0 or y1 <= y0:
                    continue
                image_rects.append((x0, y0, x1, y1))
            page_formats.append(PageFormatInfo(
                page_index=page_index,
                width=width,
                height=height,
                orientation=orientation,
                image_rects=image_rects,
            ))
    return page_formats


def infer_page_format_profile(page_formats: list[PageFormatInfo]) -> PageFormatProfile | None:
    if not page_formats:
        return None
    width_counts: dict[tuple[int, int, str], list[int]] = {}
    for pf in page_formats:
        key = (int(round(pf.width)), int(round(pf.height)), pf.orientation)
        width_counts.setdefault(key, []).append(pf.page_index)
    canonical_key, canonical_pages = max(width_counts.items(), key=lambda item: len(item[1]))
    canonical_width, canonical_height, canonical_orientation = canonical_key

    total = len(page_formats)
    if total >= 40:
        start = total // 4
        end = (3 * total) // 4
    elif total >= 12:
        start = total // 3
        end = (2 * total) // 3
    else:
        start = 0
        end = total
    window_pages = set(range(start, end))
    profile_page_indexes = [
        pf.page_index
        for pf in page_formats
        if pf.page_index in window_pages
        and int(round(pf.width)) == canonical_width
        and int(round(pf.height)) == canonical_height
        and pf.orientation == canonical_orientation
    ]
    if not profile_page_indexes:
        profile_page_indexes = [
            pf.page_index
            for pf in page_formats
            if int(round(pf.width)) == canonical_width
            and int(round(pf.height)) == canonical_height
            and pf.orientation == canonical_orientation
        ]
    return PageFormatProfile(
        canonical_width=float(canonical_width),
        canonical_height=float(canonical_height),
        canonical_orientation=canonical_orientation,
        profile_page_indexes=profile_page_indexes,
    )


def _smooth(values: list[float], window: int = 5) -> list[float]:
    if not values or window <= 1:
        return values[:]
    radius = window // 2
    smoothed: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - radius)
        hi = min(len(values), i + radius + 1)
        smoothed.append(_mean(values[lo:hi]))
    return smoothed


# -----------------------------------------------------------------------------
# Public extraction API
# -----------------------------------------------------------------------------


def extract_page_blocks(pdf_path: Path) -> tuple[list[PageBlock], int, float, float]:
    """
    Extrahiert PyMuPDF-Blöcke als reine Python-Primitive.
    Diese Funktion muss öffentlich bleiben, weil pipeline.py sie importiert.
    """
    blocks: list[PageBlock] = []

    with fitz.open(pdf_path) as doc:
        if len(doc) == 0:
            raise ValueError(f"Empty PDF: {pdf_path}")

        first_page = doc.load_page(0)
        paper_width = float(first_page.rect.width)
        paper_height = float(first_page.rect.height)
        page_count = len(doc)

        for page_index in range(page_count):
            page = doc.load_page(page_index)
            raw_blocks = page.get_text("blocks")

            for block_index, raw in enumerate(raw_blocks):
                x0, y0, x1, y1, text, _block_no, block_type = raw[:7]

                blocks.append(
                    PageBlock(
                        page_index=int(page_index),
                        block_index=int(block_index),
                        block_type=int(block_type),
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        text=str(text or ""),
                    )
                )

    return blocks, page_count, paper_width, paper_height


# -----------------------------------------------------------------------------
# Column detection from lines
# -----------------------------------------------------------------------------


def extract_text_line_boxes(
    pdf_path: Path,
    page_body_regions: list[BodyRegion | None],
) -> list[ColumnBox]:
    """
    Extrahiert horizontale Textzeilen im jeweiligen Seiten-Body.

    Wichtig:
    - Nur Text aus page.get_text("dict")
    - Keine Bilder / drawings / image blocks
    """
    boxes: list[ColumnBox] = []

    with fitz.open(pdf_path) as doc:
        for page_index in range(len(doc)):
            body_region = page_body_regions[page_index]
            if body_region is None:
                continue

            page = doc.load_page(page_index)
            clip = fitz.Rect(
                body_region.x0,
                body_region.y0,
                body_region.x1,
                body_region.y1,
            )

            data = page.get_text(
                "dict",
                flags=fitz.TEXTFLAGS_TEXT,
                clip=clip,
            )

            parity = "odd" if _is_odd_page(page_index) else "even"

            for block in data.get("blocks", []):
                if "lines" not in block:
                    continue

                for line in block["lines"]:
                    if tuple(line.get("dir", (1, 0))) != (1, 0):
                        continue

                    bbox = line.get("bbox")
                    if not bbox:
                        continue

                    x0, y0, x1, y1 = map(float, bbox)
                    if x1 <= x0 or y1 <= y0:
                        continue

                    text = "".join(
                        span.get("text", "").strip()
                        for span in line.get("spans", [])
                    ).strip()
                    if len(text) < 2:
                        continue

                    boxes.append(
                        ColumnBox(
                            page_index=page_index,
                            parity=parity,
                            x0=x0,
                            y0=y0,
                            x1=x1,
                            y1=y1,
                        )
                    )

    return boxes


def build_column_compatible_boxes(
    line_boxes: list[ColumnBox],
    page_body_regions: list[BodyRegion | None],
) -> list[ColumnBox]:
    """
    Verschmilzt zeilenweise Boxen seitenlokal zu spaltenkompatiblen Boxen.
    Nur auf Textzeilenbasis.
    """
    page_map: dict[int, list[ColumnBox]] = {}
    for box in line_boxes:
        page_map.setdefault(box.page_index, []).append(box)

    merged_all: list[ColumnBox] = []

    for page_index, boxes in page_map.items():
        body_region = page_body_regions[page_index]
        if body_region is None:
            continue

        boxes = sorted(boxes, key=lambda b: (b.y0, b.x0))
        merged: list[ColumnBox] = []

        for box in boxes:
            if box.width > body_region.width * 0.75:
                continue

            attached = False

            for i, existing in enumerate(merged):
                overlap = min(existing.x1, box.x1) - max(existing.x0, box.x0)
                min_width = max(1.0, min(existing.width, box.width))
                overlap_ratio = overlap / min_width if min_width > 0 else 0.0

                vertical_gap = box.y0 - existing.y1

                same_lane = overlap_ratio >= 0.35
                near_enough = vertical_gap <= max(existing.height, box.height) * 1.5

                if same_lane and near_enough:
                    merged[i] = ColumnBox(
                        page_index=existing.page_index,
                        parity=existing.parity,
                        x0=min(existing.x0, box.x0),
                        y0=min(existing.y0, box.y0),
                        x1=max(existing.x1, box.x1),
                        y1=max(existing.y1, box.y1),
                    )
                    attached = True
                    break

            if not attached:
                merged.append(box)

        merged_all.extend(merged)

    return merged_all


def split_line_boxes_by_page_role(
    line_boxes: list[ColumnBox],
    page_body_regions: list[BodyRegion | None],
    min_width_abs: float = 20.0,
    wide_width_ratio: float = 0.68,
) -> tuple[
    dict[int, list[tuple[float, float]]],
    dict[int, list[tuple[float, float]]],
]:
    candidate_by_page: dict[int, list[tuple[float, float]]] = {}
    wide_by_page: dict[int, list[tuple[float, float]]] = {}

    for box in line_boxes:
        body = page_body_regions[box.page_index]
        if body is None:
            continue

        if box.width < min_width_abs:
            continue

        x0_rel = (box.x0 - body.x0) / max(1e-6, body.width)
        x1_rel = (box.x1 - body.x0) / max(1e-6, body.width)

        x0_rel = max(0.0, min(1.0, x0_rel))
        x1_rel = max(0.0, min(1.0, x1_rel))

        if x1_rel <= x0_rel:
            continue

        width_rel = x1_rel - x0_rel

        if width_rel >= wide_width_ratio:
            wide_by_page.setdefault(box.page_index, []).append((x0_rel, x1_rel))
        else:
            candidate_by_page.setdefault(box.page_index, []).append((x0_rel, x1_rel))

    return candidate_by_page, wide_by_page


def _cluster_positions_1d(
    values: list[float],
    tolerance: float = 0.06,
    min_cluster_size: int = 2,
) -> list[float]:
    if not values:
        return []

    values = sorted(values)
    clusters: list[list[float]] = [[values[0]]]

    for value in values[1:]:
        if abs(value - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    centers = [
        _median(cluster)
        for cluster in clusters
        if len(cluster) >= min_cluster_size
    ]
    return centers


def page_column_hypothesis(
    page_lines_rel: list[tuple[float, float]],
    wide_lines_rel: list[tuple[float, float]] | None = None,
    bins: int = 80,
    threshold_ratio: float = 0.25,
    min_lane_width_rel: float = 0.12,
) -> tuple[int, list[tuple[float, float]], float]:
    wide_lines_rel = wide_lines_rel or []

    if not page_lines_rel:
        return 0, [], 0.0

    occupied = [0] * bins

    for x0_rel, x1_rel in page_lines_rel:
        start = max(0, min(bins - 1, int(x0_rel * bins)))
        end = max(0, min(bins - 1, int(x1_rel * bins)))
        for i in range(start, end + 1):
            occupied[i] += 1

    max_occ = max(occupied) if occupied else 0
    if max_occ == 0:
        return 0, [], 0.0

    threshold = max_occ * threshold_ratio
    occ = _smooth([float(v) for v in occupied], window=5)

    lanes: list[tuple[float, float]] = []
    i = 0
    while i < bins:
        if occ[i] < threshold:
            i += 1
            continue

        j = i
        while j + 1 < bins and occ[j + 1] >= threshold:
            j += 1

        x0_rel = i / bins
        x1_rel = (j + 1) / bins

        if (x1_rel - x0_rel) >= min_lane_width_rel:
            lanes.append((x0_rel, x1_rel))

        i = j + 1

    left_edges = [x0 for x0, _x1 in page_lines_rel]
    x0_clusters = _cluster_positions_1d(
        left_edges,
        tolerance=0.06,
        min_cluster_size=max(2, int(len(left_edges) * 0.15)),
    )

    occupancy_count = len(lanes)
    cluster_count = len(x0_clusters)

    inferred_count = max(occupancy_count, cluster_count, 1)

    if inferred_count > 2:
        inferred_count = 2

    if occupancy_count == 1 and cluster_count >= 2:
        inferred_count = 2

    widths = [x1 - x0 for x0, x1 in lanes] if lanes else []
    wide_ratio = len(wide_lines_rel) / max(1, len(page_lines_rel) + len(wide_lines_rel))

    score = 0.0
    score += min(1.0, 0.35 * inferred_count)
    score += min(0.35, 0.35 * _mean(widths)) if widths else 0.0
    score += min(0.30, 0.15 * cluster_count)
    score -= min(0.15, 0.10 * wide_ratio)

    score = max(0.0, min(1.0, score))

    if inferred_count >= 2 and len(lanes) <= 1 and len(x0_clusters) >= 2:
        centers = sorted(x0_clusters[:inferred_count])
        synthetic: list[tuple[float, float]] = []
        for idx, center in enumerate(centers):
            if idx + 1 < len(centers):
                right = min(1.0, (center + centers[idx + 1]) / 2.0)
            else:
                right = 1.0
            left = center
            if right - left >= min_lane_width_rel:
                synthetic.append((left, right))
        if synthetic:
            lanes = synthetic

    if not lanes and inferred_count == 1:
        return 1, [], max(score, 0.1)

    return inferred_count, lanes, score


def build_page_column_hypotheses(
    line_boxes: list[ColumnBox],
    page_body_regions: list[BodyRegion | None],
    page_count: int,
) -> list[PageColumnHypothesis]:
    candidate_by_page, wide_by_page = split_line_boxes_by_page_role(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
    )

    hypotheses: list[PageColumnHypothesis] = []

    for page_index in range(page_count):
        page_lines = candidate_by_page.get(page_index, [])
        wide_lines = wide_by_page.get(page_index, [])

        count, lanes, score = page_column_hypothesis(
            page_lines_rel=page_lines,
            wide_lines_rel=wide_lines,
        )

        if page_index <= 1 and len(page_lines) < 12:
            count = 1
            lanes = []
            score = min(score, 0.5)

        hypotheses.append(
            PageColumnHypothesis(
                page_index=page_index,
                column_count=max(1, count) if (page_lines or wide_lines) else 0,
                lane_ranges_rel=lanes,
                score=score,
                candidate_line_count=len(page_lines),
                wide_line_count=len(wide_lines),
            )
        )

    return hypotheses


def summarize_page_column_hypotheses(
    hypotheses: list[PageColumnHypothesis],
    page_count: int,
) -> dict[str, object]:
    nonzero = [h for h in hypotheses if h.column_count > 0]
    if not nonzero:
        return {
            "dominant_column_count": 0,
            "coverage_by_count": {},
            "mean_score": 0.0,
            "has_secondary_two_column_mode": False,
            "two_column_coverage": 0.0,
            "mixed_layout": False,
        }

    coverage_by_count: dict[int, int] = {}
    for hyp in nonzero:
        coverage_by_count[hyp.column_count] = coverage_by_count.get(hyp.column_count, 0) + 1

    dominant_column_count = max(
        coverage_by_count.items(),
        key=lambda item: item[1],
    )[0]

    coverage_by_count_ratio = {
        k: v / page_count for k, v in sorted(coverage_by_count.items())
    }

    two_column_coverage = coverage_by_count_ratio.get(2, 0.0)
    has_secondary_two_column_mode = two_column_coverage >= 0.20
    mixed_layout = (
        coverage_by_count_ratio.get(1, 0.0) >= 0.30
        and two_column_coverage >= 0.20
    )

    return {
        "dominant_column_count": dominant_column_count,
        "coverage_by_count": coverage_by_count_ratio,
        "mean_score": _mean([h.score for h in nonzero]),
        "has_secondary_two_column_mode": has_secondary_two_column_mode,
        "two_column_coverage": two_column_coverage,
        "mixed_layout": mixed_layout,
    }


def _relative_lane_intervals(
    boxes: list[ColumnBox],
    page_body_regions: list[BodyRegion | None],
) -> list[tuple[str, float, float, int]]:
    result: list[tuple[str, float, float, int]] = []

    for box in boxes:
        body = page_body_regions[box.page_index]
        if body is None:
            continue

        body_width = max(1e-6, body.width)
        x0_rel = (box.x0 - body.x0) / body_width
        x1_rel = (box.x1 - body.x0) / body_width

        x0_rel = max(0.0, min(1.0, x0_rel))
        x1_rel = max(0.0, min(1.0, x1_rel))

        if x1_rel <= x0_rel:
            continue

        if (x1_rel - x0_rel) >= 0.72:
            continue

        result.append((box.parity, x0_rel, x1_rel, box.page_index))

    return result


def _detect_lanes_from_intervals(
    intervals: list[tuple[str, float, float, int]],
    page_count: int,
    parity: str,
    bins: int = 120,
) -> list[ColumnLane]:
    if parity == "odd":
        intervals = [it for it in intervals if it[0] == "odd"]
        eligible_pages = len([p for p in range(page_count) if _is_odd_page(p)])
    elif parity == "even":
        intervals = [it for it in intervals if it[0] == "even"]
        eligible_pages = len([p for p in range(page_count) if not _is_odd_page(p)])
    else:
        eligible_pages = page_count

    if not intervals or eligible_pages == 0:
        return []

    pages_per_bin: list[set[int]] = [set() for _ in range(bins)]

    for _parity, x0_rel, x1_rel, page_index in intervals:
        start = max(0, min(bins - 1, int(x0_rel * bins)))
        end = max(0, min(bins - 1, int(x1_rel * bins)))

        for i in range(start, end + 1):
            pages_per_bin[i].add(page_index)

    raw_coverage = [len(s) / eligible_pages for s in pages_per_bin]
    page_coverage = _smooth(raw_coverage, window=5)

    threshold = 0.18
    lanes: list[ColumnLane] = []
    i = 0
    lane_index = 0

    while i < bins:
        if page_coverage[i] < threshold:
            i += 1
            continue

        j = i
        while j + 1 < bins and page_coverage[j + 1] >= threshold:
            j += 1

        x0_rel = i / bins
        x1_rel = (j + 1) / bins
        pages_present = len(set().union(*pages_per_bin[i:j + 1]))
        coverage_ratio = pages_present / eligible_pages
        lane_width = x1_rel - x0_rel

        if coverage_ratio >= 0.18 and lane_width >= 0.08:
            lanes.append(
                ColumnLane(
                    index=lane_index,
                    x0=x0_rel,
                    x1=x1_rel,
                    pages_present=pages_present,
                    coverage_ratio=coverage_ratio,
                    block_count=0,
                )
            )
            lane_index += 1

        i = j + 1

    return lanes


def _merge_close_or_overlapping_lanes(
    lanes: list[ColumnLane],
    body_width: float,
) -> list[ColumnLane]:
    if not lanes:
        return []

    lanes = sorted(lanes, key=lambda lane: lane.x0)
    merged: list[ColumnLane] = [lanes[0]]

    for lane in lanes[1:]:
        prev = merged[-1]

        gap = lane.x0 - prev.x1
        overlap = min(prev.x1, lane.x1) - max(prev.x0, lane.x0)
        min_width = max(1e-6, min(prev.width, lane.width))
        overlap_ratio = max(0.0, overlap) / min_width

        if gap <= body_width * 0.02 or overlap_ratio >= 0.20:
            merged[-1] = ColumnLane(
                index=prev.index,
                x0=min(prev.x0, lane.x0),
                x1=max(prev.x1, lane.x1),
                pages_present=max(prev.pages_present, lane.pages_present),
                coverage_ratio=max(prev.coverage_ratio, lane.coverage_ratio),
                block_count=max(prev.block_count, lane.block_count),
            )
        else:
            merged.append(lane)

    for i, lane in enumerate(merged):
        lane.index = i

    return merged


def detect_column_lanes(
    pdf_path: Path,
    page_body_regions: list[BodyRegion | None],
    page_count: int,
    document_body_region: BodyRegion,
) -> tuple[int, list[float], float | None, list[ColumnLane], list[ColumnBox], dict[str, object]]:
    line_boxes = extract_text_line_boxes(
        pdf_path=pdf_path,
        page_body_regions=page_body_regions,
    )

    column_boxes = build_column_compatible_boxes(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
    )

    rel_intervals = _relative_lane_intervals(
        boxes=column_boxes,
        page_body_regions=page_body_regions,
    )

    lanes_odd = _detect_lanes_from_intervals(rel_intervals, page_count, "odd")
    lanes_even = _detect_lanes_from_intervals(rel_intervals, page_count, "even")

    lanes_all: list[ColumnLane] = []

    def overlap(a: ColumnLane, b: ColumnLane) -> float:
        inter = min(a.x1, b.x1) - max(a.x0, b.x0)
        if inter <= 0:
            return 0.0
        denom = max(1e-6, min(a.width, b.width))
        return inter / denom

    used_even: set[int] = set()
    lane_index = 0

    for odd_lane in lanes_odd:
        best_j = None
        best_overlap = 0.0
        for j, even_lane in enumerate(lanes_even):
            if j in used_even:
                continue
            ov = overlap(odd_lane, even_lane)
            if ov > best_overlap:
                best_overlap = ov
                best_j = j

        if best_j is not None and best_overlap >= 0.35:
            even_lane = lanes_even[best_j]
            used_even.add(best_j)
            lanes_all.append(
                ColumnLane(
                    index=lane_index,
                    x0=min(odd_lane.x0, even_lane.x0),
                    x1=max(odd_lane.x1, even_lane.x1),
                    pages_present=max(odd_lane.pages_present, even_lane.pages_present),
                    coverage_ratio=max(odd_lane.coverage_ratio, even_lane.coverage_ratio),
                    block_count=len(column_boxes),
                )
            )
            lane_index += 1

    if not lanes_all:
        dominant = lanes_odd if len(lanes_odd) >= len(lanes_even) else lanes_even
        for lane in dominant:
            lanes_all.append(
                ColumnLane(
                    index=lane_index,
                    x0=lane.x0,
                    x1=lane.x1,
                    pages_present=lane.pages_present,
                    coverage_ratio=lane.coverage_ratio,
                    block_count=len(column_boxes),
                )
            )
            lane_index += 1

    abs_lanes: list[ColumnLane] = []
    for lane in lanes_all:
        abs_lanes.append(
            ColumnLane(
                index=lane.index,
                x0=document_body_region.x0 + lane.x0 * document_body_region.width,
                x1=document_body_region.x0 + lane.x1 * document_body_region.width,
                pages_present=lane.pages_present,
                coverage_ratio=lane.coverage_ratio,
                block_count=lane.block_count,
            )
        )

    abs_lanes = _merge_close_or_overlapping_lanes(abs_lanes, document_body_region.width)
    abs_lanes = [
        lane for lane in abs_lanes
        if lane.width >= document_body_region.width * 0.18
    ]

    abs_lanes.sort(key=lambda l: l.x0)
    for i, lane in enumerate(abs_lanes):
        lane.index = i

    column_count = len(abs_lanes) if abs_lanes else 1

    if not abs_lanes:
        widths = [document_body_region.width]
        gap = None
    else:
        widths = [lane.width for lane in abs_lanes]
        gaps = [
            max(0.0, right.x0 - left.x1)
            for left, right in zip(abs_lanes, abs_lanes[1:])
        ]
        gap = _mean(gaps) if gaps else None

    diagnostics = {
        "line_box_count": len(line_boxes),
        "column_box_count": len(column_boxes),
        "lanes_odd": [lane.to_dict() for lane in lanes_odd],
        "lanes_even": [lane.to_dict() for lane in lanes_even],
        "lanes_all_relative": [lane.to_dict() for lane in lanes_all],
    }

    if column_count == 1 and abs_lanes:
        if abs_lanes[0].width >= document_body_region.width * 0.85:
            return 1, [document_body_region.width], None, [], column_boxes, diagnostics

    if page_count < 6 and column_count > 2:
        return 1, [document_body_region.width], None, [], column_boxes, diagnostics

    return column_count, widths, gap, abs_lanes, column_boxes, diagnostics


# -----------------------------------------------------------------------------
# Layout signatures and patterns
# -----------------------------------------------------------------------------


def build_page_layout_signatures(
    blocks: list[PageBlock],
    page_body_regions: list[BodyRegion | None],
    header_band: FurnitureBand | None,
    footer_band: FurnitureBand | None,
    header_band_odd: FurnitureBand | None,
    header_band_even: FurnitureBand | None,
    footer_band_odd: FurnitureBand | None,
    footer_band_even: FurnitureBand | None,
    column_boxes: list[ColumnBox],
    page_column_hypotheses: list[PageColumnHypothesis],
    page_count: int,
    page_width: float,
    page_height: float,
    furniture_diag: dict[str, object] | None = None,
) -> list[PageLayoutSignature]:
    text_page_map = _group_by_page([b for b in blocks if _is_text_like(b)])

    box_page_map: dict[int, list[ColumnBox]] = {}
    for box in column_boxes:
        box_page_map.setdefault(box.page_index, []).append(box)

    furniture_diag = furniture_diag or {}
    header_quality = furniture_diag.get("header_quality")
    footer_quality = furniture_diag.get("footer_quality")

    signatures: list[PageLayoutSignature] = []

    for page_index in range(page_count):
        page_blocks = text_page_map.get(page_index, [])
        page_boxes = box_page_map.get(page_index, [])
        page_body = page_body_regions[page_index]
        hyp = page_column_hypotheses[page_index]

        header_band_for_page = header_band_odd if _is_odd_page(page_index) else header_band_even
        if header_band_for_page is None:
            header_band_for_page = header_band

        footer_band_for_page = footer_band_odd if _is_odd_page(page_index) else footer_band_even
        if footer_band_for_page is None:
            footer_band_for_page = footer_band

        page_has_header = decide_page_has_furniture(
            page_blocks=page_blocks,
            page_width=page_width,
            page_height=page_height,
            side="top",
            page_count=page_count,
            global_band=header_band_for_page,
            global_quality=header_quality,
            body_region=page_body,
        )

        page_has_footer = decide_page_has_furniture(
            page_blocks=page_blocks,
            page_width=page_width,
            page_height=page_height,
            side="bottom",
            page_count=page_count,
            global_band=footer_band_for_page,
            global_quality=footer_quality,
            body_region=page_body,
        )

        active_lane_ranges_abs: list[tuple[float, float]] = []
        if page_body is not None:
            for x0_rel, x1_rel in hyp.lane_ranges_rel:
                active_lane_ranges_abs.append(
                    (
                        page_body.x0 + x0_rel * page_body.width,
                        page_body.x0 + x1_rel * page_body.width,
                    )
                )

        signature = PageLayoutSignature(
            page_index=page_index,
            page_number=page_index + 1,
            parity="odd" if _is_odd_page(page_index) else "even",
            has_header=page_has_header,
            has_footer=page_has_footer,
            body_x0=page_body.x0 if page_body else None,
            body_x1=page_body.x1 if page_body else None,
            body_y0=page_body.y0 if page_body else None,
            body_y1=page_body.y1 if page_body else None,
            page_column_count=max(1, hyp.column_count) if page_body else 0,
            active_lane_indices=list(range(len(hyp.lane_ranges_rel))),
            active_lane_ranges=active_lane_ranges_abs,
            text_block_count=len(page_blocks),
            column_box_count=len(page_boxes),
            body_block_count=len(page_blocks),
        )
        signatures.append(signature)

    return signatures


def build_layout_patterns(
    signatures: list[PageLayoutSignature],
    total_pages: int,
) -> list[LayoutPattern]:
    grouped: dict[str, list[PageLayoutSignature]] = {}
    for sig in signatures:
        grouped.setdefault(sig.layout_key(), []).append(sig)

    patterns: list[LayoutPattern] = []

    for key, sigs in grouped.items():
        page_indexes = sorted(sig.page_index for sig in sigs)
        coverage_ratio = len(sigs) / max(1, total_pages)

        body_x0_values = [s.body_x0 for s in sigs if s.body_x0 is not None]
        body_x1_values = [s.body_x1 for s in sigs if s.body_x1 is not None]
        body_y0_values = [s.body_y0 for s in sigs if s.body_y0 is not None]
        body_y1_values = [s.body_y1 for s in sigs if s.body_y1 is not None]

        body_x0_stats = _robust_stats(body_x0_values)
        body_x1_stats = _robust_stats(body_x1_values)
        body_y0_stats = _robust_stats(body_y0_values)
        body_y1_stats = _robust_stats(body_y1_values)

        column_counts = [float(s.page_column_count) for s in sigs]
        col_med = _median(column_counts) if column_counts else None
        col_mad = _mad(column_counts, col_med) if column_counts else None

        mad_values = [
            stats.mad
            for stats in [body_x0_stats, body_x1_stats, body_y0_stats, body_y1_stats]
            if stats is not None
        ]
        mean_mad = _mean(mad_values) if mad_values else 0.0

        stability_score = 1.0 / (1.0 + mean_mad)

        sample_factor = min(1.0, len(sigs) / 5.0)
        coverage_score = coverage_ratio

        confidence_score = (
            0.45 * stability_score
            + 0.35 * coverage_score
            + 0.20 * sample_factor
        )

        patterns.append(
            LayoutPattern(
                key=key,
                pages_present=len(sigs),
                total_pages=total_pages,
                coverage_ratio=coverage_ratio,
                page_indexes=page_indexes,
                page_runs=_page_runs(page_indexes),
                body_x0_stats=body_x0_stats,
                body_x1_stats=body_x1_stats,
                body_y0_stats=body_y0_stats,
                body_y1_stats=body_y1_stats,
                column_count_median=col_med,
                column_count_mad=col_mad,
                stability_score=stability_score,
                confidence_score=confidence_score,
            )
        )

    patterns.sort(
        key=lambda p: (p.coverage_ratio, p.confidence_score or 0.0),
        reverse=True,
    )
    return patterns


# -----------------------------------------------------------------------------
# Public builder
# -----------------------------------------------------------------------------


def build_geometry_profile(pdf_path: Path) -> GeometryProfile:
    blocks, page_count, page_width, page_height = extract_page_blocks(pdf_path)

    image_block_count = len([b for b in blocks if b.block_type == 1])

    (
        header_band,
        footer_band,
        header_band_odd,
        header_band_even,
        footer_band_odd,
        footer_band_even,
        furniture_diag,
    ) = detect_repeated_furniture_bands(
        blocks=blocks,
        page_count=page_count,
        page_width=page_width,
        page_height=page_height,
    )

    non_furniture_blocks = filter_out_furniture(
        blocks=blocks,
        header_band=header_band,
        footer_band=footer_band,
    )

    page_body_regions = detect_page_body_regions(
        blocks=non_furniture_blocks,
        page_count=page_count,
        page_width=page_width,
        page_height=page_height,
    )

    document_body = detect_document_body_region_from_pages(
        page_regions=page_body_regions,
        page_width=page_width,
        page_height=page_height,
    )

    if document_body is None:
        document_body = BodyRegion(
            x0=0.0,
            y0=header_band.y1 if header_band else 0.0,
            x1=page_width,
            y1=footer_band.y0 if footer_band else page_height,
        )

    left_margin_zone, right_margin_zone = detect_margin_zones(
        blocks=non_furniture_blocks,
        body=document_body,
        page_count=page_count,
        page_width=page_width,
    )

    page_map = _group_by_page(non_furniture_blocks)
    refined_page_bodies: list[BodyRegion | None] = []
    for page_index in range(page_count):
        refined_page_bodies.append(
            refine_page_body_region(
                page_region=page_body_regions[page_index],
                page_blocks=page_map.get(page_index, []),
                left_margin_zone=left_margin_zone,
                right_margin_zone=right_margin_zone,
                page_width=page_width,
                page_height=page_height,
            )
        )

    page_body_regions = refined_page_bodies

    document_body = detect_document_body_region_from_pages(
        page_regions=page_body_regions,
        page_width=page_width,
        page_height=page_height,
    ) or document_body

    line_boxes = extract_text_line_boxes(
        pdf_path=pdf_path,
        page_body_regions=page_body_regions,
    )

    column_boxes = build_column_compatible_boxes(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
    )

    page_column_hypotheses = build_page_column_hypotheses(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
        page_count=page_count,
    )

    page_column_summary = summarize_page_column_hypotheses(
        hypotheses=page_column_hypotheses,
        page_count=page_count,
    )

    (
        column_count,
        column_widths,
        column_gap,
        column_lanes,
        _column_boxes_again,
        column_diag,
    ) = detect_column_lanes(
        pdf_path=pdf_path,
        page_body_regions=page_body_regions,
        page_count=page_count,
        document_body_region=document_body,
    )

    if column_count == 1:
        if page_column_summary["dominant_column_count"] > 1:
            column_count = int(page_column_summary["dominant_column_count"])
        elif page_column_summary["has_secondary_two_column_mode"]:
            column_count = 2
    column_count = max(1, min(2, column_count))

    raw_text_blocks = [b for b in blocks if _is_text_like(b)]

    page_layout_signatures = build_page_layout_signatures(
        blocks=raw_text_blocks,
        page_body_regions=page_body_regions,
        header_band=header_band,
        footer_band=footer_band,
        header_band_odd=header_band_odd,
        header_band_even=header_band_even,
        footer_band_odd=footer_band_odd,
        footer_band_even=footer_band_even,
        column_boxes=column_boxes,
        page_column_hypotheses=page_column_hypotheses,
        page_count=page_count,
        page_width=page_width,
        page_height=page_height,
        furniture_diag=furniture_diag,
    )

    layout_patterns = build_layout_patterns(
        signatures=page_layout_signatures,
        total_pages=page_count,
    )

    header_bottom = header_band.y1 if header_band else 0.0
    footer_top = footer_band.y0 if footer_band else page_height

    diagnostics = {
        "raw_block_count": len(blocks),
        "image_block_count": image_block_count,
        "text_block_count": len([b for b in blocks if _is_text_like(b)]),
        "non_furniture_text_block_count": len(non_furniture_blocks),
        "furniture_detection": furniture_diag,
        "column_detection": column_diag,
        "body_width": document_body.width,
        "body_height": document_body.height,
        "page_body_region_count": len([r for r in page_body_regions if r is not None]),
        "layout_pattern_count": len(layout_patterns),
        "page_column_hypotheses": [h.to_dict() for h in page_column_hypotheses],
        "page_column_summary": page_column_summary,
    }

    return GeometryProfile(
        page_count=page_count,
        paper_width=page_width,
        paper_height=page_height,
        text_left=document_body.x0,
        text_right=document_body.x1,
        text_top=document_body.y0,
        text_bottom=document_body.y1,
        header_bottom=header_bottom,
        footer_top=footer_top,
        margin_left=document_body.x0,
        margin_right=max(0.0, page_width - document_body.x1),
        column_count=column_count,
        column_widths=column_widths,
        column_gap=column_gap,
        column_lanes=column_lanes,
        header_band=header_band,
        footer_band=footer_band,
        header_band_odd=header_band_odd,
        header_band_even=header_band_even,
        footer_band_odd=footer_band_odd,
        footer_band_even=footer_band_even,
        left_margin_zone=left_margin_zone,
        right_margin_zone=right_margin_zone,
        body_region=document_body,
        page_body_regions=page_body_regions,
        page_layout_signatures=page_layout_signatures,
        layout_patterns=layout_patterns,
        diagnostics=diagnostics,
    )



@dataclass(slots=True)
class DocumentGeometryProfile:
    page_count: int
    paper_width: float
    paper_height: float
    body_region: BodyRegion | None
    page_body_regions: list[BodyRegion | None]
    furniture_profile: FurnitureProfile
    vertical_profile: VerticalProfile
    page_formats: list[object] = field(default_factory=list)
    page_format_profile: object | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageGeometryObservation:
    page_index: int
    furniture: PageFurnitureObservation | None
    vertical: PageVerticalObservation | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageGeometryMatch:
    page_index: int
    matches_profile: bool
    furniture_match: FurnitureMatch | None
    vertical_match: VerticalMatch | None
    deviation_score: float
    deviation_types: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def build_document_geometry_profile(pdf_path: Path) -> tuple[DocumentGeometryProfile, list[PageGeometryObservation]]:
    blocks, page_count, page_width, page_height = extract_page_blocks(pdf_path)
    page_formats = extract_page_formats(pdf_path)
    page_format_profile = infer_page_format_profile(page_formats)
    page_image_rects: dict[int, list[tuple[float, float, float, float]]] = {pf.page_index: pf.image_rects for pf in page_formats}
    profile_page_indexes = page_format_profile.profile_page_indexes if page_format_profile is not None else None
    filtered_blocks = filter_text_blocks_overlapping_images(blocks, page_image_rects)
    page_body_regions = detect_page_body_regions(filtered_blocks, page_count, page_width, page_height)
    document_body = detect_document_body_region_from_pages(page_body_regions, page_width, page_height)
    if document_body is None:
        document_body = BodyRegion(0.0, 0.0, page_width, page_height)
    left_margin_zone, right_margin_zone = detect_margin_zones(filtered_blocks, document_body, page_count, page_width)
    page_map = _group_by_page(filtered_blocks)
    page_body_regions = [
        refine_page_body_region(page_body_regions[i], page_map.get(i, []), left_margin_zone, right_margin_zone, page_width, page_height)
        for i in range(page_count)
    ]
    document_body = detect_document_body_region_from_pages(page_body_regions, page_width, page_height) or document_body

    furniture_profile, furniture_observations = infer_furniture_profile(
        blocks=filtered_blocks,
        page_count=page_count,
        page_width=page_width,
        page_height=page_height,
        page_body_regions=page_body_regions,
        page_image_rects=page_image_rects,
        profile_page_indexes=profile_page_indexes,
    )
    vertical_profile, vertical_observations, _column_boxes = infer_vertical_profile(
        pdf_path=pdf_path,
        page_body_regions=page_body_regions,
        page_count=page_count,
        document_body_region=document_body,
        page_image_rects=page_image_rects,
        profile_page_indexes=profile_page_indexes,
    )
    observations = [
        PageGeometryObservation(
            page_index=i,
            furniture=furniture_observations[i] if i < len(furniture_observations) else None,
            vertical=vertical_observations[i] if i < len(vertical_observations) else None,
        )
        for i in range(page_count)
    ]
    profile = DocumentGeometryProfile(
        page_count=page_count,
        paper_width=page_width,
        paper_height=page_height,
        body_region=document_body,
        page_body_regions=page_body_regions,
        furniture_profile=furniture_profile,
        vertical_profile=vertical_profile,
        page_formats=page_formats,
        page_format_profile=page_format_profile,
        diagnostics={"source_pdf": str(pdf_path), "page_format_profile": page_format_profile.to_dict() if page_format_profile else None},
    )
    return profile, observations


def match_page_to_geometry_profile(profile: DocumentGeometryProfile, observation: PageGeometryObservation) -> PageGeometryMatch:
    furniture_match = match_page_to_furniture_profile(profile.furniture_profile, observation.furniture) if observation.furniture is not None else None
    page_body = profile.page_body_regions[observation.page_index] if observation.page_index < len(profile.page_body_regions) else None
    vertical_match = match_page_to_vertical_profile(profile.vertical_profile, observation.vertical, page_body) if observation.vertical is not None else None
    deviation_types: list[str] = []
    deviation_score = 0.0
    if furniture_match is not None:
        deviation_types.extend(furniture_match.deviation_types)
        deviation_score += 0.30 * furniture_match.deviation_score
    if vertical_match is not None:
        deviation_types.extend(vertical_match.deviation_types)
        deviation_score += 0.70 * vertical_match.deviation_score
    deviation_score = min(1.0, deviation_score)
    header_expected = profile.furniture_profile.header_presence_ratio >= 0.5
    footer_expected = profile.furniture_profile.footer_presence_ratio >= 0.5
    furniture_ok = True
    if furniture_match is not None:
        if header_expected and not furniture_match.header_match:
            furniture_ok = False
        if footer_expected and not furniture_match.footer_match:
            furniture_ok = False
    vertical_ok = vertical_match.column_match if vertical_match is not None else True
    matches_profile = vertical_ok and furniture_ok
    return PageGeometryMatch(
        page_index=observation.page_index,
        matches_profile=matches_profile,
        furniture_match=furniture_match,
        vertical_match=vertical_match,
        deviation_score=deviation_score,
        deviation_types=sorted(set(t for t in deviation_types if t)),
    )
