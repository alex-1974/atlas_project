"""
atlas.parse.zones

Furniture-Erkennung (Header/Footer), Body-Region und Margin-Zonen.

Kernidee:
    Blöcke einer Seite werden nach y0 sortiert und durch Weißraum in
    horizontale Bänder aufgeteilt. Das oberste Band ist ein Header-Kandidat,
    das unterste ein Footer-Kandidat. Über die Mittelseiten des Dokuments
    wird die häufigste Band-Position per Median ermittelt; MAD bestimmt
    die Kohärenz-Schwelle.

Kein Scoring, keine Dokumentklassen-Parameter, keine hartcodierten Grenzen.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import NamedTuple

from atlas.parse.logging import get_logger
from ._utils import (
    _clamp,
    _is_odd_page,
    _is_text_like,
    _mad,
    _mad_tolerance,
    _median,
    _middle_page_indexes,
    _percentile,
    _rect_intersection_area,
)


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodelle
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FurnitureBand:
    side: str           # "top" | "bottom"
    y0: float
    y1: float
    coverage_ratio: float
    pages_present: int
    page_parity: str = "all"   # "all" | "odd" | "even"

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MarginZone:
    side: str           # "left" | "right"
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
class PageFurnitureObservation:
    page_index: int
    parity: str
    has_header: bool
    has_footer: bool
    header_band: FurnitureBand | None = None
    footer_band: FurnitureBand | None = None
    header_score: float = 0.0
    footer_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FurnitureProfile:
    page_count: int
    profile_pages: list[int]
    header_band: FurnitureBand | None = None
    footer_band: FurnitureBand | None = None
    header_band_odd: FurnitureBand | None = None
    header_band_even: FurnitureBand | None = None
    footer_band_odd: FurnitureBand | None = None
    footer_band_even: FurnitureBand | None = None
    header_presence_ratio: float = 0.0
    footer_presence_ratio: float = 0.0
    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FurnitureMatch:
    page_index: int
    header_match: bool
    footer_match: bool
    deviation_score: float
    deviation_types: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class _Band(NamedTuple):
    """Internes Ergebnis der seitenweisen Band-Segmentierung."""
    y0: float
    y1: float


# ---------------------------------------------------------------------------
# Statistische Hilfsfunktionen
# ---------------------------------------------------------------------------


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


# ---------------------------------------------------------------------------
# Block-Utilities
# ---------------------------------------------------------------------------


def _group_by_page(blocks: list[object]) -> dict[int, list[object]]:
    pages: dict[int, list[object]] = {}
    for block in blocks:
        pages.setdefault(block.page_index, []).append(block)
    return pages


# ---------------------------------------------------------------------------
# Kern: Seitenweise Band-Segmentierung
# ---------------------------------------------------------------------------


def _merge_blocks_into_bands(
    page_blocks: list[object],
    page_height: float,
    merge_tol_rel: float = 0.008,
) -> list[_Band]:
    """
    Sortiert Textblöcke nach y0 und mergt überlappende oder nahe Blöcke
    zu horizontalen Bändern.

    Merge-Kriterium: y0[i+1] < y1[i] + tol
    wobei tol = page_height × merge_tol_rel (relativ zur Seitenhöhe).

    x-Koordinaten werden ignoriert — nur die vertikale Ausdehnung zählt.
    """
    text_blocks = [b for b in page_blocks if _is_text_like(b)]
    if not text_blocks:
        return []

    tol = page_height * merge_tol_rel
    sorted_blocks = sorted(text_blocks, key=lambda b: float(b.y0))

    bands: list[_Band] = []
    current_y0 = float(sorted_blocks[0].y0)
    current_y1 = float(sorted_blocks[0].y1)

    for block in sorted_blocks[1:]:
        b_y0 = float(block.y0)
        b_y1 = float(block.y1)

        if b_y0 <= current_y1 + tol:
            # Überlappend oder nah genug → Band erweitern
            current_y1 = max(current_y1, b_y1)
        else:
            # Weißraum → Band abschließen, neues beginnen
            bands.append(_Band(y0=current_y0, y1=current_y1))
            current_y0 = b_y0
            current_y1 = b_y1

    bands.append(_Band(y0=current_y0, y1=current_y1))
    return bands


def _header_candidate(bands: list[_Band]) -> _Band | None:
    """Oberstes Band = Header-Kandidat."""
    return bands[0] if bands else None


def _footer_candidate(bands: list[_Band]) -> _Band | None:
    """Unterstes Band = Footer-Kandidat."""
    # Nur wenn mindestens zwei Bänder existieren — sonst ist das einzige
    # Band der Body, nicht der Footer.
    return bands[-1] if len(bands) >= 2 else None


# ---------------------------------------------------------------------------
# Aggregation über Seiten: Median + MAD
# ---------------------------------------------------------------------------


def _cluster_band_candidates(
    candidates: list[tuple[int, _Band]],
    page_height: float,
) -> list[dict[str, object]]:
    """
    Clustert Band-Kandidaten über Seiten nach y0/y1-Ähnlichkeit.

    Algorithmus:
    1. Median der y0-Werte aller Kandidaten
    2. MAD-Toleranz bestimmt, welche Kandidaten zum Cluster gehören
    3. Iterativ: Kandidaten außerhalb des Clusters bilden eigene Cluster

    Gibt geordnete Cluster zurück (größter zuerst).
    """
    if not candidates:
        return []

    remaining = list(candidates)
    clusters: list[dict[str, object]] = []

    while remaining:
        y0_values = [band.y0 for _, band in remaining]
        y1_values = [band.y1 for _, band in remaining]

        y0_med = _median(y0_values)
        y1_med = _median(y1_values)

        tol_y0 = _mad_tolerance(y0_values, page_height)
        tol_y1 = _mad_tolerance(y1_values, page_height)

        members = [
            (page_index, band)
            for page_index, band in remaining
            if abs(band.y0 - y0_med) <= tol_y0
            and abs(band.y1 - y1_med) <= tol_y1
        ]
        outliers = [
            item for item in remaining
            if item not in members
        ]

        if not members:
            break

        clusters.append({
            "members": members,
            "y0_med": _median([band.y0 for _, band in members]),
            "y1_med": _median([band.y1 for _, band in members]),
            "pages_present": len({page_index for page_index, _ in members}),
        })

        remaining = outliers

    clusters.sort(key=lambda c: c["pages_present"], reverse=True)
    return clusters


def _band_from_cluster(
    cluster: dict[str, object],
    side: str,
    page_parity: str,
    eligible_page_count: int,
    page_height: float,
) -> FurnitureBand | None:
    members: list[tuple[int, _Band]] = cluster["members"]
    if not members:
        return None

    pages_present = len({page_index for page_index, _ in members})

    # Mindestens 2 Seiten oder Mehrheit bei sehr kurzen Dokumenten
    if eligible_page_count >= 4 and pages_present < 2:
        return None

    y0_values = [band.y0 for _, band in members]
    y1_values = [band.y1 for _, band in members]

    # Robuste Bandgrenzen: P20 für y0, P80 für y1
    # Schließt Ausreißer aus ohne den Median zu verschieben
    y0 = _percentile(y0_values, 0.20)
    y1 = _percentile(y1_values, 0.80)

    if y1 <= y0:
        return None

    # Furniture-Bänder sind kompakt — maximal 6% der Seitenhöhe.
    # Größere Bänder sind Bodytext, kein Header/Footer.
    max_band_height = page_height * 0.06
    if (y1 - y0) > max_band_height:
        logger.debug(
            "band_from_cluster side=%s rejected: height=%.1f > max=%.1f",
            side, y1 - y0, max_band_height,
        )
        return None

    coverage_ratio = pages_present / max(1, eligible_page_count)

    logger.debug(
        "band_from_cluster side=%s parity=%s y0=%.2f y1=%.2f "
        "coverage=%.3f pages=%d/%d",
        side, page_parity, y0, y1, coverage_ratio,
        pages_present, eligible_page_count,
    )

    return FurnitureBand(
        side=side,
        y0=y0,
        y1=y1,
        coverage_ratio=coverage_ratio,
        pages_present=pages_present,
        page_parity=page_parity,
    )


def _infer_band_for_pages(
    page_map: dict[int, list[object]],
    page_indexes: list[int],
    side: str,
    page_parity: str,
    page_height: float,
) -> FurnitureBand | None:
    """
    Inferiert ein Furniture-Band für eine Menge von Seiten.

    Ablauf:
    1. Pro Seite: Blöcke → Bänder (Weißraum-Segmentierung)
    2. Header- oder Footer-Kandidat aus Bändern wählen
    3. Kandidaten über Seiten clustern (Median + MAD)
    4. Größten Cluster → FurnitureBand
    """
    if side == "top":
        parity_pages = [
            p for p in page_indexes
            if page_parity == "all"
            or (page_parity == "odd" and _is_odd_page(p))
            or (page_parity == "even" and not _is_odd_page(p))
        ]
    else:
        parity_pages = [
            p for p in page_indexes
            if page_parity == "all"
            or (page_parity == "odd" and _is_odd_page(p))
            or (page_parity == "even" and not _is_odd_page(p))
        ]

    if not parity_pages:
        return None

    candidates: list[tuple[int, _Band]] = []

    for page_index in parity_pages:
        blocks = page_map.get(page_index, [])
        bands = _merge_blocks_into_bands(blocks, page_height)

        if side == "top":
            candidate = _header_candidate(bands)
        else:
            candidate = _footer_candidate(bands)

        if candidate is not None:
            candidates.append((page_index, candidate))

    if not candidates:
        return None

    clusters = _cluster_band_candidates(candidates, page_height)
    if not clusters:
        return None

    return _band_from_cluster(
        clusters[0],
        side=side,
        page_parity=page_parity,
        eligible_page_count=len(parity_pages),
        page_height=page_height,
    )


# ---------------------------------------------------------------------------
# Seitenweise Matching gegen das Profil
# ---------------------------------------------------------------------------


def _page_has_furniture(
    page_blocks: list[object],
    page_height: float,
    side: str,
    band: FurnitureBand | None,
) -> bool:
    """
    Entscheidet, ob eine Seite einen Header/Footer hat.

    Logik:
    - Kein globales Band → kein Furniture
    - Blöcke → Bänder segmentieren
    - Prüfen ob der Kandidat (oben/unten) mit dem globalen Band übereinstimmt
      (innerhalb der MAD-basierten Toleranz des Bands)
    """
    if band is None:
        return False

    bands = _merge_blocks_into_bands(page_blocks, page_height)

    if side == "top":
        candidate = _header_candidate(bands)
    else:
        candidate = _footer_candidate(bands)

    if candidate is None:
        return False

    # Toleranz: 1% der Seitenhöhe — enger als beim Profil-Clustering,
    # weil wir jetzt gegen ein bereits robustes Profil matchen
    tol = page_height * 0.012

    matches = (
        abs(candidate.y0 - band.y0) <= tol
        and abs(candidate.y1 - band.y1) <= tol
    )

    logger.debug(
        "page_has_furniture side=%s candidate=(%.2f, %.2f) "
        "band=(%.2f, %.2f) tol=%.2f matches=%s",
        side, candidate.y0, candidate.y1,
        band.y0, band.y1, tol, matches,
    )

    return matches


# ---------------------------------------------------------------------------
# Öffentliche API: infer_furniture_profile
# ---------------------------------------------------------------------------


def infer_furniture_profile(
    blocks: list[object],
    page_count: int,
    page_width: float,
    page_height: float,
    page_body_regions: list[BodyRegion | None] | None = None,
    page_image_rects: dict[int, list[tuple[float, float, float, float]]] | None = None,
    profile_page_indexes: list[int] | None = None,
) -> tuple[FurnitureProfile, list[PageFurnitureObservation]]:
    """
    Inferiert das Furniture-Profil (Header/Footer) eines Dokuments.

    Analyse-Seiten: mittleres Drittel des Dokuments (oder profile_page_indexes).
    Parity: odd/even separat, dann zusammengeführt falls kein Unterschied.
    """
    filtered_blocks = filter_text_blocks_overlapping_images(blocks, page_image_rects)
    text_blocks = [b for b in filtered_blocks if _is_text_like(b)]
    page_map = _group_by_page(text_blocks)

    # Profilseiten: mindestens 3, nach Textdichte gefiltert.
    # Seiten ohne Textblöcke (Vollbild, Leerseiten) liefern kein Furniture-Signal.
    MIN_PROFILE_PAGES = 3
    MIN_BLOCKS_PER_PAGE = 2

    candidate_pages = (
        profile_page_indexes
        if profile_page_indexes is not None and len(profile_page_indexes) >= MIN_PROFILE_PAGES
        else _middle_page_indexes(page_count)
    )

    profile_pages = [
        p for p in candidate_pages
        if len(page_map.get(p, [])) >= MIN_BLOCKS_PER_PAGE
    ]

    # Fallback auf gesamtes Dokument wenn mittleres Drittel zu wenige Textseiten hat
    if len(profile_pages) < MIN_PROFILE_PAGES:
        profile_pages = [
            p for p in range(page_count)
            if len(page_map.get(p, [])) >= MIN_BLOCKS_PER_PAGE
        ]
        if len(profile_pages) > MIN_PROFILE_PAGES:
            profile_pages = [p for p in profile_pages if p >= min(2, page_count // 10)]

    if not profile_pages:
        profile_pages = list(range(page_count))

    logger.debug(
        "furniture profile_pages: %d textreiche Seiten (von %d Kandidaten)",
        len(profile_pages), len(candidate_pages),
    )

    # --- Profil-Inferenz ---

    header_all  = _infer_band_for_pages(page_map, profile_pages, "top",    "all",  page_height)
    header_odd  = _infer_band_for_pages(page_map, profile_pages, "top",    "odd",  page_height)
    header_even = _infer_band_for_pages(page_map, profile_pages, "top",    "even", page_height)
    footer_all  = _infer_band_for_pages(page_map, profile_pages, "bottom", "all",  page_height)
    footer_odd  = _infer_band_for_pages(page_map, profile_pages, "bottom", "odd",  page_height)
    footer_even = _infer_band_for_pages(page_map, profile_pages, "bottom", "even", page_height)

    # Wenn odd und even ähnlich sind, bevorzuge all
    header_band = header_all or _merge_bands([header_odd, header_even], "top")
    footer_band = footer_all or _merge_bands([footer_odd, footer_even], "bottom")

    logger.debug(
        "furniture_profile header=%s footer=%s profile_pages=%d",
        header_band.to_dict() if header_band else None,
        footer_band.to_dict() if footer_band else None,
        len(profile_pages),
    )

    # --- Seitenweise Observations ---

    observations: list[PageFurnitureObservation] = []
    header_pages = 0
    footer_pages = 0

    for page_index in range(page_count):
        page_blocks = page_map.get(page_index, [])
        parity = "odd" if _is_odd_page(page_index) else "even"

        local_header = (
            (header_odd if parity == "odd" else header_even)
            or header_band
        )
        local_footer = (
            (footer_odd if parity == "odd" else footer_even)
            or footer_band
        )

        has_header = _page_has_furniture(page_blocks, page_height, "top",    local_header)
        has_footer = _page_has_furniture(page_blocks, page_height, "bottom", local_footer)

        if has_header:
            header_pages += 1
        if has_footer:
            footer_pages += 1

        observations.append(PageFurnitureObservation(
            page_index=page_index,
            parity=parity,
            has_header=has_header,
            has_footer=has_footer,
            header_band=local_header if has_header else None,
            footer_band=local_footer if has_footer else None,
        ))

    diagnostics = {
        "profile_pages": [p + 1 for p in profile_pages],
        "header_all": header_all.to_dict() if header_all else None,
        "header_odd": header_odd.to_dict() if header_odd else None,
        "header_even": header_even.to_dict() if header_even else None,
        "footer_all": footer_all.to_dict() if footer_all else None,
        "footer_odd": footer_odd.to_dict() if footer_odd else None,
        "footer_even": footer_even.to_dict() if footer_even else None,
    }

    profile = FurnitureProfile(
        page_count=page_count,
        profile_pages=list(profile_pages),
        header_band=header_band,
        footer_band=footer_band,
        header_band_odd=header_odd,
        header_band_even=header_even,
        footer_band_odd=footer_odd,
        footer_band_even=footer_even,
        header_presence_ratio=header_pages / max(1, page_count),
        footer_presence_ratio=footer_pages / max(1, page_count),
        diagnostics=diagnostics,
    )

    return profile, observations


# ---------------------------------------------------------------------------
# Öffentliche API: detect_repeated_furniture_bands (Wrapper für Kompatibilität)
# ---------------------------------------------------------------------------


def match_page_to_furniture_profile(
    profile: FurnitureProfile,
    observation: PageFurnitureObservation,
) -> FurnitureMatch:
    deviation_types: list[str] = []
    expected_header = profile.header_presence_ratio >= 0.5
    expected_footer = profile.footer_presence_ratio >= 0.5

    header_match = observation.has_header == expected_header
    footer_match = observation.has_footer == expected_footer

    if not header_match:
        deviation_types.append("missing_header" if expected_header else "unexpected_header")
    if not footer_match:
        deviation_types.append("missing_footer" if expected_footer else "unexpected_footer")

    deviation_score = (0.5 if not header_match else 0.0) + (0.5 if not footer_match else 0.0)

    return FurnitureMatch(
        page_index=observation.page_index,
        header_match=header_match,
        footer_match=footer_match,
        deviation_score=min(1.0, deviation_score),
        deviation_types=deviation_types,
    )


# ---------------------------------------------------------------------------
# Öffentliche API: decide_page_has_furniture (Wrapper für geometry.py)
# ---------------------------------------------------------------------------


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
    return [
        detect_page_body_region(page_map.get(i, []), page_width, page_height)
        for i in range(page_count)
    ]


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

    usable = [
        b for b in page_blocks
        if _is_text_like(b)
        and not (left_margin_zone and float(b.x1) <= left_margin_zone.x1)
        and not (right_margin_zone and float(b.x0) >= right_margin_zone.x0)
    ]

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


def _merge_bands(
    bands: list[FurnitureBand | None],
    side: str,
) -> FurnitureBand | None:
    """Führt odd/even-Bänder zusammen, wenn beide vorhanden."""
    valid = [b for b in bands if b is not None]
    if not valid:
        return None
    return FurnitureBand(
        side=side,
        y0=min(b.y0 for b in valid),
        y1=max(b.y1 for b in valid),
        coverage_ratio=max(b.coverage_ratio for b in valid),
        pages_present=max(b.pages_present for b in valid),
        page_parity="all",
    )


def filter_text_blocks_overlapping_images(
    blocks: list[object],
    page_image_rects: dict[int, list[tuple[float, float, float, float]]] | None,
    overlap_threshold: float = 0.50,
) -> list[object]:
    if not page_image_rects:
        return list(blocks)
    filtered: list[object] = []
    for block in blocks:
        image_rects = page_image_rects.get(block.page_index, [])
        if not image_rects or not _is_text_like(block):
            filtered.append(block)
            continue
        block_rect = (float(block.x0), float(block.y0), float(block.x1), float(block.y1))
        block_area = max(0.0, block_rect[2] - block_rect[0]) * max(0.0, block_rect[3] - block_rect[1])
        if block_area <= 0:
            filtered.append(block)
            continue
        max_ratio = max(
            (_rect_intersection_area(block_rect, ir) / block_area for ir in image_rects),
            default=0.0,
        )
        if max_ratio < overlap_threshold:
            filtered.append(block)
    return filtered


