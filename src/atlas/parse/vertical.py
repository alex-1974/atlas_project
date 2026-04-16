from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

import pymupdf as fitz  # PyMuPDF

from .zones import BodyRegion


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
class VerticalCandidate:
    """
    Seitenlokaler vertikaler Kandidat innerhalb des Body.

    Anders als bei Header/Footer ist hier nicht nur die x-Lage wichtig,
    sondern auch die robuste vertikale Ausdehnung. Genau darüber trennen
    wir Spalten von Marginalien.
    """

    page_index: int
    parity: str
    x0_rel: float
    x1_rel: float
    y0_rel: float
    y1_rel: float
    width_rel: float
    height_rel: float
    coverage_rel: float
    block_count: int

    def to_dict(self) -> dict:
        return asdict(self)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


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


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _smooth(values: list[float], window: int = 5) -> list[float]:
    if not values or window <= 1:
        return values[:]
    radius = window // 2
    result: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - radius)
        hi = min(len(values), i + radius + 1)
        result.append(_mean(values[lo:hi]))
    return result


def _is_odd_page(page_index: int) -> bool:
    return (page_index + 1) % 2 == 1


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
    Verschmilzt zeilenweise Boxen seitenlokal zu vertikal kompatiblen Boxen.

    Ziel:
    - seitenlokale vertikale Bahnen aufbauen
    - breite Volltextzeilen nicht blind als Lane-Signal dominieren lassen
    """
    page_map: dict[int, list[ColumnBox]] = {}
    for box in line_boxes:
        page_map.setdefault(box.page_index, []).append(box)

    merged_all: list[ColumnBox] = []

    for page_index, boxes in page_map.items():
        body_region = page_body_regions[page_index]
        if body_region is None:
            continue

        boxes = sorted(boxes, key=lambda b: (b.x0, b.y0))
        merged: list[ColumnBox] = []

        for box in boxes:
            if box.width > body_region.width * 0.90:
                continue

            attached = False

            for i, existing in enumerate(merged):
                overlap = min(existing.x1, box.x1) - max(existing.x0, box.x0)
                min_width = max(1.0, min(existing.width, box.width))
                overlap_ratio = max(0.0, overlap) / min_width if min_width > 0 else 0.0

                x_center_delta = abs(
                    ((existing.x0 + existing.x1) / 2.0)
                    - ((box.x0 + box.x1) / 2.0)
                )

                same_lane = (
                    overlap_ratio >= 0.45
                    or x_center_delta <= max(existing.width, box.width) * 0.18
                )
                vertically_reachable = (
                    box.y0 <= existing.y1 + max(existing.height, box.height) * 3.0
                )

                if same_lane and vertically_reachable:
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


def _build_page_vertical_candidates_map(
    column_boxes: list[ColumnBox],
    page_body_regions: list[BodyRegion | None],
) -> dict[int, list[VerticalCandidate]]:
    """
    Baut seitenlokale vertikale Kandidaten im Body.

    Idee:
    - x-ähnliche Boxen pro Seite gruppieren
    - deren vertikale Ausdehnung bestimmen
    - niedrige/kurze Bahnen später statistisch als Marginalien aussortieren
    """
    page_map: dict[int, list[ColumnBox]] = {}
    for box in column_boxes:
        page_map.setdefault(box.page_index, []).append(box)

    result: dict[int, list[VerticalCandidate]] = {}

    for page_index, boxes in page_map.items():
        body = page_body_regions[page_index]
        if body is None or body.width <= 0 or body.height <= 0:
            continue

        filtered = [
            b for b in boxes
            if b.width >= body.width * 0.08
            and b.height >= body.height * 0.04
        ]
        if not filtered:
            continue

        filtered = sorted(filtered, key=lambda b: (b.x0, b.y0))
        groups: list[list[ColumnBox]] = []

        for box in filtered:
            attached = False

            for group in groups:
                gx0 = min(b.x0 for b in group)
                gx1 = max(b.x1 for b in group)
                g_center = (gx0 + gx1) / 2.0
                box_center = (box.x0 + box.x1) / 2.0

                overlap = min(gx1, box.x1) - max(gx0, box.x0)
                min_width = max(1.0, min(gx1 - gx0, box.width))
                overlap_ratio = max(0.0, overlap) / min_width
                center_delta = abs(g_center - box_center)

                if overlap_ratio >= 0.35 or center_delta <= body.width * 0.08:
                    group.append(box)
                    attached = True
                    break

            if not attached:
                groups.append([box])

        candidates: list[VerticalCandidate] = []

        for group in groups:
            x0 = min(b.x0 for b in group)
            x1 = max(b.x1 for b in group)
            y0 = min(b.y0 for b in group)
            y1 = max(b.y1 for b in group)

            width_rel = (x1 - x0) / body.width
            height_rel = (y1 - y0) / body.height

            if width_rel < 0.08:
                continue
            if height_rel < 0.12:
                continue

            x0_rel = (x0 - body.x0) / body.width
            x1_rel = (x1 - body.x0) / body.width
            y0_rel = (y0 - body.y0) / body.height
            y1_rel = (y1 - body.y0) / body.height

            x0_rel = max(0.0, min(1.0, x0_rel))
            x1_rel = max(0.0, min(1.0, x1_rel))
            y0_rel = max(0.0, min(1.0, y0_rel))
            y1_rel = max(0.0, min(1.0, y1_rel))

            candidates.append(
                VerticalCandidate(
                    page_index=page_index,
                    parity="odd" if _is_odd_page(page_index) else "even",
                    x0_rel=x0_rel,
                    x1_rel=x1_rel,
                    y0_rel=y0_rel,
                    y1_rel=y1_rel,
                    width_rel=width_rel,
                    height_rel=height_rel,
                    coverage_rel=height_rel,
                    block_count=len(group),
                )
            )

        candidates.sort(key=lambda c: (-c.coverage_rel, c.x0_rel))
        result[page_index] = candidates[:4]

    return result


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

    return [
        _median(cluster)
        for cluster in clusters
        if len(cluster) >= min_cluster_size
    ]


def _page_occupancy_hypothesis(
    page_lines_rel: list[tuple[float, float]],
    wide_lines_rel: list[tuple[float, float]] | None = None,
    bins: int = 80,
    threshold_ratio: float = 0.25,
    min_lane_width_rel: float = 0.12,
) -> tuple[int, list[tuple[float, float]], float]:
    """
    Frühere Occupancy-Idee als Hilfssignal:
    kollabieren über y und suchen Häufungen nach x.
    """
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

    return inferred_count, lanes, score


def build_page_column_hypotheses(
    line_boxes: list[ColumnBox],
    page_body_regions: list[BodyRegion | None],
    page_count: int,
) -> list[PageColumnHypothesis]:
    """
    Seitenweise Hypothese auf Basis eines Hybridmodells:

    1. Vertikale Kandidaten (Spalten höher als Marginalien)
    2. Occupancy über x als Stabilisierungssignal
    """
    column_boxes = build_column_compatible_boxes(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
    )
    candidate_map = _build_page_vertical_candidates_map(
        column_boxes=column_boxes,
        page_body_regions=page_body_regions,
    )

    wide_line_count_by_page: dict[int, int] = {}
    line_count_by_page: dict[int, int] = {}
    occupancy_lines_by_page: dict[int, list[tuple[float, float]]] = {}
    wide_occupancy_lines_by_page: dict[int, list[tuple[float, float]]] = {}

    for box in line_boxes:
        line_count_by_page[box.page_index] = line_count_by_page.get(box.page_index, 0) + 1
        body = page_body_regions[box.page_index]
        if body is None or body.width <= 0:
            continue

        x0_rel = (box.x0 - body.x0) / body.width
        x1_rel = (box.x1 - body.x0) / body.width
        x0_rel = max(0.0, min(1.0, x0_rel))
        x1_rel = max(0.0, min(1.0, x1_rel))
        if x1_rel <= x0_rel:
            continue

        width_rel = x1_rel - x0_rel
        if width_rel >= 0.68:
            wide_line_count_by_page[box.page_index] = (
                wide_line_count_by_page.get(box.page_index, 0) + 1
            )
            wide_occupancy_lines_by_page.setdefault(box.page_index, []).append((x0_rel, x1_rel))
        elif width_rel >= 0.04:
            occupancy_lines_by_page.setdefault(box.page_index, []).append((x0_rel, x1_rel))

    hypotheses: list[PageColumnHypothesis] = []

    for page_index in range(page_count):
        candidates = candidate_map.get(page_index, [])
        tall = [c for c in candidates if c.coverage_rel >= 0.45]
        very_tall = [c for c in candidates if c.coverage_rel >= 0.62]

        if len(very_tall) >= 2:
            vertical_selected = sorted(very_tall, key=lambda c: c.x0_rel)[:2]
        elif len(tall) >= 2:
            vertical_selected = sorted(tall, key=lambda c: c.x0_rel)[:2]
        elif tall:
            vertical_selected = [max(tall, key=lambda c: c.coverage_rel)]
        elif candidates:
            vertical_selected = [max(candidates, key=lambda c: c.coverage_rel)]
        else:
            vertical_selected = []

        occ_count, occ_lanes, occ_score = _page_occupancy_hypothesis(
            occupancy_lines_by_page.get(page_index, []),
            wide_occupancy_lines_by_page.get(page_index, []),
        )

        vertical_count = len(vertical_selected)
        vertical_lanes = [(c.x0_rel, c.x1_rel) for c in vertical_selected]

        if vertical_count == 0 and occ_count > 0:
            final_count = occ_count
            final_lanes = occ_lanes[:2]
        elif vertical_count > 0 and occ_count == 0:
            final_count = vertical_count
            final_lanes = vertical_lanes[:2]
        elif vertical_count > 0 and occ_count > 0:
            if occ_count > vertical_count and occ_score >= 0.45:
                final_count = occ_count
                final_lanes = occ_lanes[:2]
            else:
                final_count = vertical_count
                final_lanes = vertical_lanes[:2]
        else:
            final_count = 0
            final_lanes = []

        if page_index <= 1 and line_count_by_page.get(page_index, 0) < 12 and final_count > 1:
            final_count = 1
            final_lanes = final_lanes[:1]

        score = 0.0
        if vertical_selected:
            score += min(0.65, 0.25 * len(vertical_selected) + 0.40 * _mean([c.coverage_rel for c in vertical_selected]))
            score += min(0.15, 0.04 * _mean([c.block_count for c in vertical_selected]))
        score += min(0.20, 0.20 * occ_score)
        score = max(0.0, min(1.0, score))

        hypotheses.append(
            PageColumnHypothesis(
                page_index=page_index,
                column_count=final_count,
                lane_ranges_rel=final_lanes,
                score=score,
                candidate_line_count=line_count_by_page.get(page_index, 0),
                wide_line_count=wide_line_count_by_page.get(page_index, 0),
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


def _cluster_vertical_candidates(
    candidates: list[VerticalCandidate],
    *,
    x_tol_rel: float,
    w_tol_rel: float,
) -> list[dict[str, object]]:
    """
    Dokumentweite Clusterung nach x-Lage und Breite.

    Analog zur Furniture-Erkennung:
    diesmal aber nicht y-Bänder, sondern vertikale x-Bahnen.
    """
    clusters: list[dict[str, object]] = []

    for cand in candidates:
        assigned = False

        for cluster in clusters:
            if (
                abs(cand.x0_rel - cluster["x0_med"]) <= x_tol_rel
                and abs(cand.x1_rel - cluster["x1_med"]) <= x_tol_rel
                and abs(cand.width_rel - cluster["w_med"]) <= w_tol_rel
            ):
                cluster["members"].append(cand)
                cluster["x0_med"] = _median([m.x0_rel for m in cluster["members"]])
                cluster["x1_med"] = _median([m.x1_rel for m in cluster["members"]])
                cluster["w_med"] = _median([m.width_rel for m in cluster["members"]])
                assigned = True
                break

        if not assigned:
            clusters.append(
                {
                    "members": [cand],
                    "x0_med": cand.x0_rel,
                    "x1_med": cand.x1_rel,
                    "w_med": cand.width_rel,
                }
            )

    return clusters


def _score_vertical_cluster(
    cluster: dict[str, object],
    *,
    page_count: int,
) -> float:
    """
    Bewertet einen dokumentweiten x-Cluster.

    Hybrid-Idee:
    - globale Präsenz
    - robuste Höhe
    - stabile x-Lage/Breite
    - aber keine harten Ausschlüsse außer völlig unplausiblen Fällen
    """
    members: list[VerticalCandidate] = cluster["members"]
    if not members:
        return -1e9

    pages_present = len({m.page_index for m in members})
    coverage_ratio = pages_present / max(1, page_count)

    x0_values = [m.x0_rel for m in members]
    x1_values = [m.x1_rel for m in members]
    width_values = [m.width_rel for m in members]
    height_values = [m.coverage_rel for m in members]

    x_stability = max(x0_values) - min(x0_values) + max(x1_values) - min(x1_values)
    w_stability = max(width_values) - min(width_values)

    height_med = _median(height_values)
    height_p25 = _percentile(height_values, 0.25)
    width_med = _median(width_values)

    if coverage_ratio < 0.03:
        return -1e9
    if width_med < 0.04:
        return -1e9

    score = (
        5.0 * coverage_ratio
        + 3.0 * height_med
        + 3.0 * height_p25
        + 2.0 * width_med
        - 4.0 * x_stability
        - 2.0 * w_stability
    )

    if coverage_ratio < 0.08:
        score -= 1.5
    if height_med < 0.15:
        score -= 1.5
    if width_med < 0.06:
        score -= 1.0

    return score


def _clusters_overlap(
    a: tuple[float, float],
    b: tuple[float, float],
    tol: float = 0.02,
) -> bool:
    return max(a[0], b[0]) <= min(a[1], b[1]) + tol


def _select_best_column_clusters(
    clusters: list[dict[str, object]],
    *,
    page_count: int,
    max_columns: int = 3,
) -> list[dict[str, object]]:
    scored: list[tuple[float, dict[str, object]]] = []
    for cluster in clusters:
        score = _score_vertical_cluster(cluster, page_count=page_count)
        if score > 0:
            scored.append((score, cluster))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected: list[dict[str, object]] = []
    selected_ranges: list[tuple[float, float]] = []

    for score, cluster in scored:
        x_range = (cluster["x0_med"], cluster["x1_med"])
        if any(_clusters_overlap(x_range, existing) for existing in selected_ranges):
            continue

        selected.append(cluster | {"score": score})
        selected_ranges.append(x_range)

        if len(selected) >= max_columns:
            break

    selected.sort(key=lambda c: c["x0_med"])
    return selected


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
    """
    Dokumentweite Spaltenerkennung.

    Hybrid-Leitidee:
    - seitenlokale vertikale Kandidaten innerhalb des Body erzeugen
    - nach x-Lage dokumentweit clustern
    - die robusten Cluster als Spalten wählen
    - Seitenhypothesen als Rückfall- und Stabilisierungssignal verwenden
    """
    line_boxes = extract_text_line_boxes(
        pdf_path=pdf_path,
        page_body_regions=page_body_regions,
    )

    column_boxes = build_column_compatible_boxes(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
    )

    candidate_map = _build_page_vertical_candidates_map(
        column_boxes=column_boxes,
        page_body_regions=page_body_regions,
    )

    all_candidates = [
        cand
        for candidates in candidate_map.values()
        for cand in candidates
    ]

    clusters = _cluster_vertical_candidates(
        all_candidates,
        x_tol_rel=0.08,
        w_tol_rel=0.10,
    )

    selected_clusters = _select_best_column_clusters(
        clusters,
        page_count=page_count,
        max_columns=3,
    )

    abs_lanes: list[ColumnLane] = []
    cluster_debug: list[dict[str, object]] = []

    for idx, cluster in enumerate(selected_clusters):
        members: list[VerticalCandidate] = cluster["members"]
        pages_present = len({m.page_index for m in members})
        coverage_ratio = pages_present / max(1, page_count)

        x0_abs = document_body_region.x0 + cluster["x0_med"] * document_body_region.width
        x1_abs = document_body_region.x0 + cluster["x1_med"] * document_body_region.width

        abs_lanes.append(
            ColumnLane(
                index=idx,
                x0=x0_abs,
                x1=x1_abs,
                pages_present=pages_present,
                coverage_ratio=coverage_ratio,
                block_count=sum(m.block_count for m in members),
            )
        )

        cluster_debug.append(
            {
                "index": idx,
                "score": cluster["score"],
                "x0_rel": cluster["x0_med"],
                "x1_rel": cluster["x1_med"],
                "width_rel": cluster["w_med"],
                "pages_present": pages_present,
                "coverage_ratio": coverage_ratio,
                "height_median": _median([m.coverage_rel for m in members]),
                "height_p25": _percentile([m.coverage_rel for m in members], 0.25),
            }
        )

    abs_lanes = _merge_close_or_overlapping_lanes(abs_lanes, document_body_region.width)
    abs_lanes = [
        lane for lane in abs_lanes
        if lane.width >= document_body_region.width * 0.12
    ]

    abs_lanes.sort(key=lambda l: l.x0)
    for i, lane in enumerate(abs_lanes):
        lane.index = i

    column_count = len(abs_lanes) if abs_lanes else 1

    page_hypotheses = build_page_column_hypotheses(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
        page_count=page_count,
    )
    summary = summarize_page_column_hypotheses(
        hypotheses=page_hypotheses,
        page_count=page_count,
    )
    dominant_count = int(summary.get("dominant_column_count", 1) or 1)

    if column_count == 1 and dominant_count > 1:
        column_count = dominant_count

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
        "vertical_candidate_count": len(all_candidates),
        "vertical_candidates_by_page": {
            page_index: [cand.to_dict() for cand in candidates]
            for page_index, candidates in candidate_map.items()
        },
        "vertical_clusters": cluster_debug,
        "page_column_hypotheses": [h.to_dict() for h in page_hypotheses],
        "page_column_summary": summary,
    }

    if column_count == 1 and abs_lanes:
        if abs_lanes[0].width >= document_body_region.width * 0.85:
            return 1, [document_body_region.width], None, [], column_boxes, diagnostics

    if page_count < 6 and column_count > 2:
        return 1, [document_body_region.width], None, [], column_boxes, diagnostics

    if column_count > 2:
        column_count = 2

    return column_count, widths, gap, abs_lanes, column_boxes, diagnostics
