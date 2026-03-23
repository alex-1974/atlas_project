# src/atlas/document_understanding/models.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SourceKind = Literal[
    "born_digital_pdf",
    "image_pdf",
    "hybrid_pdf",
    "plain_text",
    "unknown",
]

TextSource = Literal[
    "pdf_native",
    "ocr",
    "fallback",
    "mixed",
    "unknown",
]

GeometrySource = Literal[
    "pdf_native",
    "ocr_boxes",
    "inferred_lines",
    "none",
    "unknown",
]

ReadingOrderSource = Literal[
    "pdf_native",
    "ocr",
    "inferred",
    "unknown",
]

ZoneType = Literal[
    "header_candidate",
    "title_candidate",
    "front_matter_candidate",
    "abstract_candidate",
    "body_candidate",
    "toc_candidate",
    "references_candidate",
    "appendix_candidate",
    "artifact_candidate",
    "metadata_candidate",
    "header",
    "title_page",
    "front_matter",
    "abstract",
    "body",
    "toc",
    "references",
    "appendix",
    "figure_caption_region",
    "metadata_region",
    "artifact_region",
]


@dataclass(slots=True)
class DocumentContext:
    document_id: str

    source_kind: SourceKind = "unknown"
    text_source: TextSource = "unknown"
    geometry_source: GeometrySource = "unknown"
    reading_order_source: ReadingOrderSource = "unknown"

    has_native_text: bool = False
    has_reliable_geometry: bool = False
    has_reliable_reading_order: bool = False

    text_confidence: float | None = None
    geometry_confidence: float | None = None
    reading_order_confidence: float | None = None

    notes: str | None = None


@dataclass(slots=True)
class Page:
    document_id: str
    page_index: int

    width: float | None = None
    height: float | None = None

    image_based: bool | None = None
    native_text_present: bool | None = None
    page_confidence: float | None = None


@dataclass(slots=True)
class Block:
    document_id: str
    block_index: int

    page_index: int | None = None

    start_char: int | None = None
    end_char: int | None = None
    text: str = ""

    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None

    page_y0: float | None = None
    page_y1: float | None = None
    doc_y0: float | None = None
    doc_y1: float | None = None

    text_source: TextSource = "unknown"
    geometry_source: GeometrySource = "unknown"

    text_confidence: float | None = None
    geometry_confidence: float | None = None
    reading_order_confidence: float | None = None


@dataclass(slots=True)
class BlockGeometry:
    block_index: int

    width: float | None = None
    height: float | None = None
    center_x: float | None = None
    center_y: float | None = None

    whitespace_before: float | None = None
    whitespace_after: float | None = None

    indent_left: float | None = None
    indent_right: float | None = None
    centeredness: float | None = None
    column_hint: float | None = None

    near_page_top: float | None = None
    near_page_bottom: float | None = None


@dataclass(slots=True)
class BlockTopology:
    block_index: int

    prev_block_index: int | None = None
    next_block_index: int | None = None

    cluster_id: int | None = None
    early_block_rank: int | None = None

    is_first_on_page: bool = False
    is_last_on_page: bool = False

    before_first_running_text: bool = False
    after_toc_candidate: bool = False
    repeated_header_footer_hint: bool = False


@dataclass(slots=True)
class BlockSignals:
    block_index: int

    title_like: float = 0.0
    author_like: float = 0.0
    affiliation_like: float = 0.0
    date_like: float = 0.0

    running_text_like: float = 0.0
    heading_like: float = 0.0
    list_like: float = 0.0
    toc_like: float = 0.0
    reference_like: float = 0.0
    bibliographic_entry_like: float = 0.0
    caption_like: float = 0.0
    marker_like: float = 0.0
    parenthetical_citation_like: float = 0.0

    journal_meta_like: float = 0.0
    artifact_like: float = 0.0
    noise_like: float = 0.0


@dataclass(slots=True)
class ZoneHypothesis:
    document_id: str
    zone_type: ZoneType

    start_block_index: int
    end_block_index: int

    page_start: int | None = None
    page_end: int | None = None

    score: float = 0.0
    source: str = "unknown"


@dataclass(slots=True)
class BlockZoneMembership:
    block_index: int
    zone_type: ZoneType
    membership: float
    source: str = "unknown"


@dataclass(slots=True)
class SemanticZone:
    document_id: str
    zone_type: ZoneType

    start_block_index: int
    end_block_index: int

    page_start: int | None = None
    page_end: int | None = None

    confidence: float | None = None
    source: str = "unknown"


@dataclass(slots=True)
class DocumentMap:
    context: DocumentContext
    pages: list[Page] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    block_geometry: list[BlockGeometry] = field(default_factory=list)
    block_topology: list[BlockTopology] = field(default_factory=list)
    block_signals: list[BlockSignals] = field(default_factory=list)
    zone_hypotheses: list[ZoneHypothesis] = field(default_factory=list)
    memberships: list[BlockZoneMembership] = field(default_factory=list)
    semantic_zones: list[SemanticZone] = field(default_factory=list)
