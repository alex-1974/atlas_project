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
    decide_page_has_furniture,
)
from .vertical import (
    ColumnBox,
    ColumnLane,
    PageColumnHypothesis,
    build_column_compatible_boxes,
    build_page_column_hypotheses,
    detect_column_lanes,
    extract_text_line_boxes,
    summarize_page_column_hypotheses,
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


# -----------------------------------------------------------------------------
# Geometry model
# -----------------------------------------------------------------------------


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


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _mad(values: list[float], med: float | None = None) -> float:
    if not values:
        return 0.0
    m = med if med is not None else _median(values)
    return _median([abs(v - m) for v in values])


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


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
