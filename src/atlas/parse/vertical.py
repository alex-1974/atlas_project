"""
atlas.parse.vertical

Spaltenerkennung und Marginalienerkennung.

Kernidee:
    Textblöcke einer Seite liefern (x0, x1)-Paare. y wird kollabiert —
    nur die horizontale Lage zählt. Über die Mittelseiten des Dokuments
    werden x0-Werte geclustert; innerhalb jedes Clusters bestimmt der
    Median von x1 die Spaltenbreite. Statistisch häufige schmale Cluster
    sind Spalten, seltene Randcluster mit wenig Blöcken sind Marginalien.

Kein expliziter Breitenfilter, keine hartcodierten Schwellen.
Median und MAD skalieren von selbst.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median

import pymupdf as fitz

from .zones import BodyRegion

from atlas.parse.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodelle
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ColumnLane:
    """Dokumentweit dominante vertikale Textbahn."""
    index: int
    x0: float
    x1: float
    pages_present: int
    coverage_ratio: float
    block_count: int
    is_marginalia: bool = False

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class VerticalProfile:
    page_count: int
    profile_pages: list[int]
    dominant_column_count: int
    dominant_column_lanes: list[ColumnLane]
    dominant_gap: float | None
    marginalia_candidates: list[ColumnLane] = field(default_factory=list)
    confidence: float = 0.0
    diagnostics: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageVerticalObservation:
    page_index: int
    parity: str
    observed_column_count: int
    observed_lane_ranges: list[tuple[float, float]]
    score: float
    candidate_line_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class VerticalMatch:
    page_index: int
    column_match: bool
    observed_column_count: int
    expected_column_count: int
    matched_lane_indices: list[int]
    deviation_score: float
    deviation_types: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Statistische Hilfsfunktionen
# ---------------------------------------------------------------------------


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _mad(values: list[float], med: float | None = None) -> float:
    if not values:
        return 0.0
    m = med if med is not None else _median(values)
    return _median([abs(v - m) for v in values])


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


def _mad_tolerance(values: list[float], body_width: float, factor: float = 2.0) -> float:
    """MAD-basierte Kohärenz-Schwelle. Minimum: body_width × 0.01."""
    if not values:
        return body_width * 0.01
    med = _median(values)
    mad = _mad(values, med)
    return max(mad * factor, body_width * 0.01)


def _is_odd_page(page_index: int) -> bool:
    return (page_index + 1) % 2 == 1


def _middle_page_indexes(page_count: int) -> list[int]:
    if page_count <= 6:
        return list(range(page_count))
    start = max(0, page_count // 3)
    end = min(page_count, (2 * page_count) // 3)
    if end <= start:
        return list(range(page_count))
    return list(range(start, end))


# ---------------------------------------------------------------------------
# Block-Extraktion
# ---------------------------------------------------------------------------


def _is_text_like(block: object) -> bool:
    return (
        getattr(block, "block_type", None) == 0
        and bool(str(getattr(block, "text", "")).strip())
    )


def _rect_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def extract_blocks_in_body(
    pdf_path: Path,
    page_body_regions: list[BodyRegion | None],
    page_image_rects: dict[int, list[tuple[float, float, float, float]]] | None = None,
) -> dict[int, list[tuple[float, float]]]:
    """
    Extrahiert (x0, x1)-Paare aller Textblöcke innerhalb der Body-Region.

    y wird kollabiert — nur die horizontale Lage ist relevant.
    Blöcke, die stark mit Bildflächen überlappen, werden übersprungen.

    Gibt ein Dict {page_index: [(x0, x1), ...]} zurück.
    """
    result: dict[int, list[tuple[float, float]]] = {}

    with fitz.open(pdf_path) as doc:
        for page_index in range(len(doc)):
            body = page_body_regions[page_index]
            if body is None:
                continue

            page = doc.load_page(page_index)
            clip = fitz.Rect(body.x0, body.y0, body.x1, body.y1)
            raw_blocks = page.get_text("blocks", clip=clip)

            image_rects = (page_image_rects or {}).get(page_index, [])
            pairs: list[tuple[float, float]] = []

            for raw in raw_blocks:
                x0, y0, x1, y1, text, _block_no, block_type = raw[:7]
                if block_type != 0:
                    continue
                if not str(text).strip():
                    continue
                if x1 <= x0:
                    continue

                # Bild-Überlappung prüfen
                if image_rects:
                    block_rect = (float(x0), float(y0), float(x1), float(y1))
                    block_area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
                    if block_area > 0:
                        max_ratio = max(
                            (_rect_intersection_area(block_rect, ir) / block_area
                             for ir in image_rects),
                            default=0.0,
                        )
                        if max_ratio >= 0.50:
                            continue

                pairs.append((float(x0), float(x1)))

            if pairs:
                result[page_index] = pairs

    return result


# ---------------------------------------------------------------------------
# Kern: Breiten-basiertes Clustering mit anschließendem x0-Clustering
# ---------------------------------------------------------------------------


def _histogram_peaks(
    values: list[float],
    span_width: float,
    threshold_ratio: float = 0.15,
    min_gap_pt: float = 10.0,
) -> list[tuple[float, float]]:
    """
    Findet Peaks in einer Werteverteilung via Histogramm.

    Gibt eine Liste von (lo, hi)-Intervallen zurück, je einen pro Peak.
    Peaks mit einem Gap < min_gap_pt werden zusammengeführt.
    """
    if not values:
        return []

    bin_count = max(60, int(span_width / 5.0))
    v_min = min(values)
    v_max = max(values)
    v_span = max(v_max - v_min, 1.0)

    counts = [0] * bin_count
    for v in values:
        idx = int((v - v_min) / v_span * (bin_count - 1))
        counts[max(0, min(bin_count - 1, idx))] += 1

    max_count = max(counts)
    threshold = max_count * threshold_ratio
    active = [c >= threshold for c in counts]

    raw_peaks: list[tuple[int, int]] = []
    i = 0
    while i < bin_count:
        if not active[i]:
            i += 1
            continue
        j = i
        while j + 1 < bin_count and active[j + 1]:
            j += 1
        raw_peaks.append((i, j))
        i = j + 1

    # Kleine Gaps schließen
    min_gap_bins = max(2, int(min_gap_pt / (v_span / bin_count)))
    merged: list[tuple[int, int]] = []
    for peak in raw_peaks:
        if merged and (peak[0] - merged[-1][1]) <= min_gap_bins:
            merged[-1] = (merged[-1][0], peak[1])
        else:
            merged.append(peak)

    result: list[tuple[float, float]] = []
    for start, end in merged:
        lo = v_min + (start / bin_count) * v_span - 3.0
        hi = v_min + ((end + 1) / bin_count) * v_span + 3.0
        result.append((lo, hi))

    return result


def _find_column_width(
    triples: list[tuple[int, float, float]],
    body_width: float,
) -> tuple[float, float] | None:
    """
    Bestimmt die dominante Spaltenbreite aus allen Profilblöcken.

    Breite ist das stabilste Signal: unabhängig von Parity,
    unabhängig davon ob eine oder zwei Spalten aktiv sind.

    Gibt (w_lo, w_hi) des dominanten Breiten-Peaks zurück.
    Peaks < 20% oder > 85% der Body-Breite werden übersprungen.
    """
    widths = [x1 - x0 for _page, x0, x1 in triples if x1 > x0]
    if not widths:
        return None

    peaks = _histogram_peaks(widths, span_width=body_width)
    if not peaks:
        return None

    min_w = body_width * 0.20
    max_w = body_width * 0.85

    plausible = []
    for lo, hi in peaks:
        center = (lo + hi) / 2.0
        if min_w <= center <= max_w:
            count = sum(1 for _p, x0, x1 in triples if lo <= (x1 - x0) <= hi)
            plausible.append((count, lo, hi))

    if not plausible:
        # Fallback: breitester plausibler Peak ohne obere Grenze
        for lo, hi in sorted(peaks, key=lambda p: -(p[0] + p[1]) / 2):
            if (lo + hi) / 2 >= min_w:
                return (lo, hi)
        return None

    plausible.sort(reverse=True)
    return (plausible[0][1], plausible[0][2])


def _infer_column_positions(
    triples: list[tuple[int, float, float]],
    body_width: float,
) -> list[dict[str, object]]:
    """
    Spaltenpositions-Inferenz aus (page, x0, x1)-Tripeln.

    Algorithmus:
    1. Dominante Spaltenbreite bestimmen (stabiles Signal)
    2. Pro Seite: x0-Positionen der Blöcke mit dieser Breite
    3. Pro Seite: x0-Histogramm → Anzahl Spalten auf dieser Seite
    4. Maximale beobachtete Spaltenanzahl als Dokument-Spaltenanzahl
       (nur wenn genug Seiten diese Anzahl zeigen)
    5. x0-Median pro Spaltenposition → Spaltenkoordinaten
    6. Marginalie-Kandidaten: schmale Blöcke außerhalb der Spaltenbreite
    """
    if not triples:
        return []

    col_width_range = _find_column_width(triples, body_width)
    if col_width_range is None:
        return []

    w_lo, w_hi = col_width_range
    col_width_med = _median([
        x1 - x0 for _p, x0, x1 in triples
        if w_lo <= (x1 - x0) <= w_hi
    ])

    # Blöcke mit dominanter Breite, pro Seite
    page_x0s: dict[int, list[float]] = {}
    for page, x0, x1 in triples:
        if w_lo <= (x1 - x0) <= w_hi:
            page_x0s.setdefault(page, []).append(x0)

    if not page_x0s:
        return []

    # Pro Seite: x0-Peaks = Spalten auf dieser Seite
    page_col_counts: dict[int, int] = {}
    page_col_x0s: dict[int, list[float]] = {}

    for page, x0s in page_x0s.items():
        peaks = _histogram_peaks(
            x0s, span_width=body_width,
            min_gap_pt=col_width_med * 0.25,
        )
        page_col_counts[page] = len(peaks)
        peak_x0s = []
        for p_lo, p_hi in sorted(peaks):
            members = [x for x in x0s if p_lo <= x <= p_hi]
            if members:
                peak_x0s.append(_median(members))
        page_col_x0s[page] = peak_x0s

    # Maximale Spaltenanzahl als vorsichtiges Signal
    col_count_freq: dict[int, int] = {}
    for count in page_col_counts.values():
        col_count_freq[count] = col_count_freq.get(count, 0) + 1

    max_cols = max(page_col_counts.values())
    pages_with_max = col_count_freq.get(max_cols, 0)
    total_signal_pages = len(page_col_counts)

    # Mindestens 15% der Seiten müssen maximale Spaltenanzahl zeigen
    if pages_with_max < max(1, int(total_signal_pages * 0.15)):
        max_cols = max(col_count_freq.items(), key=lambda kv: kv[1])[0]

    # Auf maximal 3 Spalten begrenzen
    max_cols = min(max_cols, 3)

    logger.debug(
        "column_positions: col_width=%.1f max_cols=%d signal_pages=%d",
        col_width_med, max_cols, total_signal_pages,
    )

    # x0-Positionen von Seiten mit max_cols Spalten
    col_x0_lists: list[list[float]] = [[] for _ in range(max_cols)]
    for page, count in page_col_counts.items():
        if count == max_cols:
            x0s = sorted(page_col_x0s[page])
            for i, x0 in enumerate(x0s[:max_cols]):
                col_x0_lists[i].append(x0)

    clusters: list[dict[str, object]] = []
    for i, x0_list in enumerate(col_x0_lists):
        if not x0_list:
            continue
        x0_med = _median(x0_list)
        x1_med = x0_med + col_width_med

        members_with_page = [
            (p, x0, x1) for p, x0, x1 in triples
            if w_lo <= (x1 - x0) <= w_hi
            and abs(x0 - x0_med) <= body_width * 0.08
        ]
        clusters.append({
            "x0_med": x0_med,
            "x1_med": x1_med,
            "block_count": len(members_with_page),
            "members": [(x0, x1) for _p, x0, x1 in members_with_page],
            "members_with_page": members_with_page,
            "is_marginalia_candidate": False,
        })

    # Marginalie-Kandidaten: Blöcke schmal und am Rand
    margin_max_w = col_width_med * 0.60
    all_width_peaks = _histogram_peaks(
        [x1 - x0 for _p, x0, x1 in triples if x1 > x0],
        span_width=body_width,
    )
    for p_lo, p_hi in all_width_peaks:
        # Überlapp mit dominantem Peak überspringen
        if p_lo <= w_hi and p_hi >= w_lo:
            continue
        if (p_lo + p_hi) / 2 >= margin_max_w:
            continue

        margin_members = [
            (p, x0, x1) for p, x0, x1 in triples
            if p_lo <= (x1 - x0) <= p_hi
        ]
        if not margin_members:
            continue

        x0_peaks = _histogram_peaks(
            [x0 for _p, x0, _x1 in margin_members],
            span_width=body_width,
        )
        for mp_lo, mp_hi in x0_peaks:
            m = [(p, x0, x1) for p, x0, x1 in margin_members if mp_lo <= x0 <= mp_hi]
            if not m:
                continue
            clusters.append({
                "x0_med": _median([x0 for _p, x0, _x1 in m]),
                "x1_med": _median([x1 for _p, _x0, x1 in m]),
                "block_count": len(m),
                "members": [(x0, x1) for _p, x0, x1 in m],
                "members_with_page": m,
                "is_marginalia_candidate": True,
            })

    clusters.sort(
        key=lambda c: (not c["is_marginalia_candidate"], c["block_count"]),
        reverse=True,
    )
    return clusters


def _cluster_pairs(
    pairs_odd: list[tuple[float, float]],
    pairs_even: list[tuple[float, float]],
    body_width: float,
    pairs_all_with_page: list[tuple[int, float, float]] | None = None,
) -> list[dict[str, object]]:
    """Haupteinstieg: delegiert an _infer_column_positions."""
    if pairs_all_with_page:
        return _infer_column_positions(pairs_all_with_page, body_width)
    # Fallback ohne Seiteninformation
    all_pairs = pairs_odd + pairs_even
    fake_triples = [(i % 2, x0, x1) for i, (x0, x1) in enumerate(all_pairs)]
    return _infer_column_positions(fake_triples, body_width)


def _collect_pairs_for_pages(
    blocks_by_page: dict[int, list[tuple[float, float]]],
    page_indexes: list[int],
) -> list[tuple[int, float, float]]:
    """Gibt (page_index, x0, x1) für alle relevanten Seiten zurück."""
    result: list[tuple[int, float, float]] = []
    for page_index in page_indexes:
        for x0, x1 in blocks_by_page.get(page_index, []):
            result.append((page_index, x0, x1))
    return result


def _split_by_parity(
    triples: list[tuple[int, float, float]],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Trennt (page, x0, x1) nach odd/even-Parität."""
    odd:  list[tuple[float, float]] = []
    even: list[tuple[float, float]] = []
    for page, x0, x1 in triples:
        if _is_odd_page(page):
            odd.append((x0, x1))
        else:
            even.append((x0, x1))
    return odd, even


# ---------------------------------------------------------------------------
# Spalten vs. Marginalien
# ---------------------------------------------------------------------------


def _classify_clusters(
    clusters: list[dict[str, object]],
    body_x0: float,
    body_x1: float,
    body_width: float,
    page_count: int,
    profile_page_count: int,
) -> tuple[list[ColumnLane], list[ColumnLane]]:
    """
    Identifiziert gleichwertige Spalten durch paarweisen Symmetrie-Vergleich.

    Zwei Cluster sind gleichwertige Spalten wenn sie sich in Breite und
    Häufigkeit ähneln:
      - Breiten-Verhältnis:     min(w0,w1) / max(w0,w1) > 0.5
      - Häufigkeits-Verhältnis: min(c0,c1) / max(c0,c1) > 0.4

    Cluster die diesen Test nicht bestehen, werden als Nebeninhalt
    ignoriert — weder Spalte noch Marginalie.

    Ausnahme: Wenn nur ein Cluster existiert, ist er die einzige Spalte.
    """
    if not clusters:
        return [], []

    def _pages(cluster: dict) -> int:
        n = len({pi for pi, _, _ in cluster.get("members_with_page", [])})
        return n if n > 0 else max(1, cluster["block_count"] // max(1, profile_page_count // 3))

    # Einzelner Cluster → immer Spalte
    if len(clusters) == 1:
        c = clusters[0]
        x0, x1 = float(c["x0_med"]), float(c["x1_med"])
        if x1 <= x0:
            return [], []
        pages_present = _pages(c)
        lane = ColumnLane(
            index=0, x0=x0, x1=x1,
            pages_present=pages_present,
            coverage_ratio=pages_present / max(1, page_count),
            block_count=int(c["block_count"]),
            is_marginalia=False,
        )
        logger.debug("single cluster -> column x0=%.1f x1=%.1f", x0, x1)
        return [lane], []

    # Mehrere Cluster: paarweiser Symmetrie-Test gegen den haeufigsten
    primary = clusters[0]
    w_primary = float(primary["x1_med"]) - float(primary["x0_med"])
    c_primary = int(primary["block_count"])

    column_clusters: list[dict] = [primary]

    for cluster in clusters[1:]:
        x0 = float(cluster["x0_med"])
        x1 = float(cluster["x1_med"])
        if x1 <= x0:
            continue

        w = x1 - x0
        c = int(cluster["block_count"])

        width_ratio = min(w, w_primary) / max(w, w_primary, 1e-6)
        count_ratio = min(c, c_primary) / max(c, c_primary, 1e-6)

        is_marginalia_candidate = cluster.get("is_marginalia_candidate", False)

        # Gleichbreite Kandidaten (width_ratio > 0.85) sind echte Spalten,
        # auch wenn sie als Marginalie-Kandidaten markiert sind.
        # Dieser Fall tritt auf wenn zwei Spalten gleiche Breite haben
        # und beide in den gleichen Breiten-Peak fallen.
        equally_wide = width_ratio > 0.85

        is_column = (
            (not is_marginalia_candidate or equally_wide)
            and width_ratio > 0.5
            and count_ratio > 0.4
        )

        logger.debug(
            "cluster x0=%.1f x1=%.1f w=%.1f count=%d "
            "width_ratio=%.2f count_ratio=%.2f marg_cand=%s -> %s",
            x0, x1, w, c, width_ratio, count_ratio,
            is_marginalia_candidate,
            "column" if is_column else "ignored",
        )

        if is_column:
            column_clusters.append(cluster)

    # Spalten aus column_clusters bauen
    lanes: list[ColumnLane] = []
    for idx, c in enumerate(column_clusters):
        x0 = float(c["x0_med"])
        x1 = float(c["x1_med"])
        pages_present = _pages(c)
        lanes.append(ColumnLane(
            index=idx, x0=x0, x1=x1,
            pages_present=pages_present,
            coverage_ratio=pages_present / max(1, page_count),
            block_count=int(c["block_count"]),
            is_marginalia=False,
        ))

    # Marginalien: Cluster die als is_marginalia_candidate markiert sind
    # (vom Breiten-Clustering als Nebenpeak identifiziert) UND am Rand liegen.
    marginalia: list[ColumnLane] = []
    margin_edge_tol = body_width * 0.15

    for cluster in clusters:
        x0 = float(cluster["x0_med"])
        x1 = float(cluster["x1_med"])
        if x1 <= x0:
            continue
        # Bereits als Spalte erfasst? Überspringen.
        if any(abs(l.x0 - x0) < body_width * 0.05
               and abs(l.x1 - x1) < body_width * 0.05
               for l in lanes):
            continue

        is_candidate = cluster.get("is_marginalia_candidate", False)
        at_left  = x0 <= body_x0 + margin_edge_tol
        at_right = x1 >= body_x1 - margin_edge_tol

        if is_candidate and (at_left or at_right):
            pages_present = _pages(cluster)
            marginalia.append(ColumnLane(
                index=len(marginalia),
                x0=x0, x1=x1,
                pages_present=pages_present,
                coverage_ratio=pages_present / max(1, page_count),
                block_count=int(cluster["block_count"]),
                is_marginalia=True,
            ))
            logger.debug(
                "marginalia x0=%.1f x1=%.1f w=%.1f at_left=%s at_right=%s",
                x0, x1, x1 - x0, at_left, at_right,
            )

    return lanes, marginalia


def _merge_overlapping_lanes(
    lanes: list[ColumnLane],
    body_width: float,
) -> list[ColumnLane]:
    """Führt überlappende oder sehr nahe Spalten zusammen."""
    if not lanes:
        return []

    lanes = sorted(lanes, key=lambda l: l.x0)
    merged = [lanes[0]]

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
                block_count=prev.block_count + lane.block_count,
                is_marginalia=False,
            )
        else:
            merged.append(lane)

    for i, lane in enumerate(merged):
        lane.index = i

    return merged


# ---------------------------------------------------------------------------
# Seitenweise Observation
# ---------------------------------------------------------------------------


def _observe_page_columns(
    pairs: list[tuple[float, float]],
    profile_lanes: list[ColumnLane],
    body_width: float,
    page_index: int,
) -> PageVerticalObservation:
    """
    Vergleicht die Blöcke einer Seite mit dem dokumentweiten Profil.

    Eine Profil-Spur gilt als "vorhanden" wenn mindestens ein Block
    der Seite innerhalb der Spur-Grenzen liegt (mit kleiner Toleranz).
    """
    tol = body_width * 0.04
    observed_ranges: list[tuple[float, float]] = []

    for lane in profile_lanes:
        present = any(
            x0 >= lane.x0 - tol and x1 <= lane.x1 + tol
            for x0, x1 in pairs
        )
        if present:
            observed_ranges.append((lane.x0, lane.x1))

    score = len(observed_ranges) / max(1, len(profile_lanes)) if profile_lanes else 0.0

    return PageVerticalObservation(
        page_index=page_index,
        parity="odd" if _is_odd_page(page_index) else "even",
        observed_column_count=len(observed_ranges),
        observed_lane_ranges=observed_ranges,
        score=score,
        candidate_line_count=len(pairs),
    )


# ---------------------------------------------------------------------------
# Öffentliche API: infer_vertical_profile
# ---------------------------------------------------------------------------


def infer_vertical_profile(
    pdf_path: Path,
    page_body_regions: list[BodyRegion | None],
    page_count: int,
    document_body_region: BodyRegion,
    page_image_rects: dict[int, list[tuple[float, float, float, float]]] | None = None,
    profile_page_indexes: list[int] | None = None,
) -> tuple[VerticalProfile, list[PageVerticalObservation], list[object]]:
    """
    Inferiert das vertikale Profil (Spalten + Marginalien) eines Dokuments.

    Ablauf:
    1. (x0, x1)-Paare aller Textblöcke im Body extrahieren
    2. Auf Profilseiten (mittleres Drittel) beschränken
    3. x0-Clustering mit Median + MAD
    4. Spalten vs. Marginalien klassifizieren
    5. Seitenweise Observations gegen Profil
    """
    MIN_PROFILE_PAGES = 3
    if profile_page_indexes is not None and len(profile_page_indexes) >= MIN_PROFILE_PAGES:
        candidate_pages = profile_page_indexes
    else:
        candidate_pages = _middle_page_indexes(page_count)

    blocks_by_page = extract_blocks_in_body(
        pdf_path=pdf_path,
        page_body_regions=page_body_regions,
        page_image_rects=page_image_rects,
    )

    # Profilseiten nach Textdichte filtern:
    # Seiten mit weniger als 4 Textblöcken sind Bild-, Kapitel- oder Leerseiten
    # und liefern kein repräsentatives Signal.
    MIN_BLOCKS_PER_PROFILE_PAGE = 4
    profile_pages = [
        p for p in candidate_pages
        if len(blocks_by_page.get(p, [])) >= MIN_BLOCKS_PER_PROFILE_PAGE
    ]

    # Falls zu wenige textile Seiten im mittleren Drittel: auf gesamtes Dokument ausweiten
    if len(profile_pages) < MIN_PROFILE_PAGES:
        profile_pages = [
            p for p in range(page_count)
            if len(blocks_by_page.get(p, [])) >= MIN_BLOCKS_PER_PROFILE_PAGE
        ]
        # Titelseiten und erste Seiten tendenziell ausschließen
        if len(profile_pages) > MIN_PROFILE_PAGES:
            profile_pages = [p for p in profile_pages if p >= min(2, page_count // 10)]

    # Notfall-Fallback: alle Seiten mit irgendeinem Text
    if not profile_pages:
        profile_pages = [p for p in range(page_count) if blocks_by_page.get(p)]

    logger.debug(
        "profile_pages: %d textreiche Seiten (von %d Kandidaten)",
        len(profile_pages), len(candidate_pages),
    )

    # Nur Profilseiten für Clustering
    profile_triples = _collect_pairs_for_pages(blocks_by_page, profile_pages)

    body_width = document_body_region.width

    # x1-Clustering, odd/even getrennt, dann zusammenführen
    pairs_odd, pairs_even = _split_by_parity(profile_triples)
    clusters = _cluster_pairs(
        pairs_odd, pairs_even, body_width,
        pairs_all_with_page=profile_triples,
    )

    # Seiteninformation in Cluster zurückschreiben für coverage
    for cluster in clusters:
        x1_med = float(cluster["x1_med"])
        tol = body_width * 0.08
        cluster["members_with_page"] = [
            (page, x0, x1)
            for page, x0, x1 in profile_triples
            if abs(x1 - x1_med) <= tol
        ]

    lanes, marginalia = _classify_clusters(
        clusters=clusters,
        body_x0=document_body_region.x0,
        body_x1=document_body_region.x1,
        body_width=body_width,
        page_count=page_count,
        profile_page_count=len(profile_pages),
    )

    lanes = _merge_overlapping_lanes(lanes, body_width)

    # Maximale Spaltenanzahl: 2 — mehr ist für wissenschaftliche Literatur
    # nicht realistisch und deutet auf Clustering-Artefakte hin
    if len(lanes) > 2:
        lanes = sorted(lanes, key=lambda l: l.block_count, reverse=True)[:2]
        lanes = sorted(lanes, key=lambda l: l.x0)
        for i, lane in enumerate(lanes):
            lane.index = i

    column_count = len(lanes) if lanes else 1

    gaps = [
        max(0.0, right.x0 - left.x1)
        for left, right in zip(lanes, lanes[1:])
    ]
    dominant_gap = _mean(gaps) if gaps else None

    confidence = _mean([
        len({p for p, _, _ in c.get("members_with_page", [])}) / max(1, len(profile_pages))
        for c in clusters[:column_count]
    ]) if clusters else 0.0

    logger.debug(
        "vertical_profile columns=%d gap=%s confidence=%.3f "
        "profile_pages=%d marginalia=%d",
        column_count, dominant_gap, confidence,
        len(profile_pages), len(marginalia),
    )

    # Seitenweise Observations
    observations: list[PageVerticalObservation] = []
    for page_index in range(page_count):
        pairs = blocks_by_page.get(page_index, [])
        obs = _observe_page_columns(pairs, lanes, body_width, page_index)
        observations.append(obs)

    diagnostics = {
        "profile_pages": [p + 1 for p in profile_pages],
        "cluster_count": len(clusters),
        "clusters": [
            {
                "x0_med": float(c["x0_med"]),
                "x1_med": float(c["x1_med"]),
                "block_count": int(c["block_count"]),
            }
            for c in clusters
        ],
        "column_lanes": [l.to_dict() for l in lanes],
        "marginalia": [l.to_dict() for l in marginalia],
    }

    profile = VerticalProfile(
        page_count=page_count,
        profile_pages=list(profile_pages),
        dominant_column_count=column_count,
        dominant_column_lanes=lanes,
        dominant_gap=dominant_gap,
        marginalia_candidates=marginalia,
        confidence=confidence,
        diagnostics=diagnostics,
    )

    return profile, observations, []


# ---------------------------------------------------------------------------
# Öffentliche API: match_page_to_vertical_profile
# ---------------------------------------------------------------------------


def _range_overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0])
    if inter <= 0:
        return 0.0
    denom = max(1e-6, min(a[1] - a[0], b[1] - b[0]))
    return inter / denom


def match_page_to_vertical_profile(
    profile: VerticalProfile,
    observation: PageVerticalObservation,
    page_body_region: BodyRegion | None,
) -> VerticalMatch:
    expected = int(profile.dominant_column_count or 0)
    observed = int(observation.observed_column_count or 0)

    expected_ranges: list[tuple[float, float]] = [
        (lane.x0, lane.x1) for lane in profile.dominant_column_lanes
    ]

    matched_lane_indices: list[int] = []
    for i, exp_range in enumerate(expected_ranges):
        if any(
            _range_overlap_ratio(exp_range, obs_range) >= 0.50
            for obs_range in observation.observed_lane_ranges
        ):
            matched_lane_indices.append(i)

    deviation_types: list[str] = []
    deviation_score = 0.0

    if observed < expected:
        deviation_types.append("missing_columns")
        deviation_score += 0.75
    elif observed > expected:
        deviation_types.append("extra_columns")
        deviation_score += 0.45

    if expected_ranges and len(matched_lane_indices) < min(expected, len(expected_ranges)):
        deviation_types.append("lane_position_mismatch")
        deviation_score += 0.35

    if expected <= 1:
        column_match = observed == expected
    else:
        column_match = (
            observed == expected
            and len(matched_lane_indices) >= min(expected, len(expected_ranges))
        )

    return VerticalMatch(
        page_index=observation.page_index,
        column_match=column_match,
        observed_column_count=observed,
        expected_column_count=expected,
        matched_lane_indices=matched_lane_indices,
        deviation_score=min(1.0, deviation_score),
        deviation_types=deviation_types,
    )


# ---------------------------------------------------------------------------
# Kompatibilitäts-Wrapper für geometry.py
# ---------------------------------------------------------------------------
