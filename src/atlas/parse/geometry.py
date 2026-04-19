from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf as fitz

from .zones import (
    BodyRegion,
    FurnitureBand,
    FurnitureMatch,
    FurnitureProfile,
    MarginZone,
    PageFurnitureObservation,
    detect_document_body_region_from_pages,
    detect_margin_zones,
    detect_page_body_regions,
    filter_text_blocks_overlapping_images,
    infer_furniture_profile,
    match_page_to_furniture_profile,
    refine_page_body_region,
)
from .vertical import (
    ColumnLane,
    PageVerticalObservation,
    VerticalMatch,
    VerticalProfile,
    infer_vertical_profile,
    match_page_to_vertical_profile,
)


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
    page_map: dict[int, list] = {}
    for b in filtered_blocks:
        page_map.setdefault(b.page_index, []).append(b)
    page_body_regions = [
        refine_page_body_region(
            page_body_regions[i], page_map.get(i, []),
            left_margin_zone, right_margin_zone,
            page_width, page_height,
        )
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
