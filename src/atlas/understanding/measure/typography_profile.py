# src/atlas/understanding/measure/typography_profile.py
"""Document-relative typography profiling.

Builds a TypographyProfile from all blocks of a document before any
role classification happens. All subsequent signal computation uses
these document-relative values instead of absolute thresholds.

Architecture
------------
1. Measure font sizes and gaps across all blocks
2. Identify body_font (dominant font — largest cluster by character count)
3. Compute font_ratio for each block: block_font / body_font
4. Cluster font_ratios into typography classes (body, sub, h3, h2, h1, ...)
5. Compute gap_norm: median paragraph_gap_before across all body blocks
6. Identify TOC blocks if present — these anchor heading level assignments

All measurements are document-relative, making them independent of the
absolute font sizes used in any particular document.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from typing import Any

from atlas.core.logging import get_logger

_log = get_logger("atlas.du.typography_profile")


# ── Safe helpers ──────────────────────────────────────────────────────────────

def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d

def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v) if v is not None else d
    except (TypeError, ValueError):
        return d


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FontClass:
    """A cluster of blocks sharing similar typographic properties.

    font_ratio is relative to body_font:
        1.0  = body text
        >1.0 = larger than body (heading candidate)
        <1.0 = smaller than body (footnote, caption label)
    """
    label: str                   # "body", "h1", "h2", ... or "small"
    font_ratio_min: float
    font_ratio_max: float
    bold: bool | None            # None = mixed
    is_all_caps: bool | None     # None = mixed
    block_count: int = 0
    char_count: int = 0
    heading_level: int | None = None  # 1-based, None if not a heading class


@dataclass
class TypographyProfile:
    """Document-relative typography measurements.

    Created once per document before role classification.
    Passed into compute_signals() and interpret/roles.py.
    """
    document_id: str

    # ── Body font ──────────────────────────────────────────────────────────────
    body_font: float = 10.0      # dominant font size in pt
    body_bold: bool = False      # is body text bold? (unusual but possible)

    # ── Gap norms ─────────────────────────────────────────────────────────────
    gap_norm: float = 5.0        # median paragraph_gap_before across body blocks
    gap_p75: float = 10.0        # 75th percentile — above this = significant gap
    gap_p90: float = 15.0        # 90th percentile — above this = major gap

    # ── Font classes (sorted by font_ratio descending) ────────────────────────
    font_classes: list[FontClass] = field(default_factory=list)

    # ── TOC anchor ────────────────────────────────────────────────────────────
    has_toc: bool = False
    toc_max_level: int = 0       # deepest level in TOC (1-based)

    # ── Flow norm ─────────────────────────────────────────────────────────────
    # in_flow_score threshold above which a block is considered embedded
    # in running text regardless of typography
    flow_threshold: float = 0.85

    def font_ratio(self, font_size: float) -> float:
        """Compute font_ratio relative to body_font."""
        if self.body_font <= 0:
            return 1.0
        return font_size / self.body_font

    def heading_class_for(self, font_size: float, bold: bool,
                           all_caps: bool) -> FontClass | None:
        """Return the heading FontClass for this typography, or None."""
        ratio = self.font_ratio(font_size)
        for fc in self.font_classes:
            if fc.heading_level is None:
                continue
            if (fc.font_ratio_min <= ratio <= fc.font_ratio_max
                    and (fc.bold is None or fc.bold == bold)
                    and (fc.is_all_caps is None or fc.is_all_caps == all_caps)):
                return fc
        return None

    def is_body_class(self, font_size: float) -> bool:
        ratio = self.font_ratio(font_size)
        return 0.85 <= ratio <= 1.15

    def relative_gap(self, gap: float) -> float:
        """Gap relative to gap_norm. >1.0 means larger than typical."""
        if self.gap_norm <= 0:
            return 1.0
        return gap / self.gap_norm


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_span_stats(conn: sqlite3.Connection,
                      document_id: str) -> list[dict]:
    """Fetch font size and char count per block from layout spans."""
    return [dict(r) for r in conn.execute(
        """
        SELECT
            b.block_id,
            b.block_index,
            b.page_index,
            COALESCE(t.font_size, 0.0)           AS font_size,
            COALESCE(t.bold, 0)                   AS bold,
            COALESCE(sf.is_all_caps, 0)           AS is_all_caps,
            COALESCE(sf.char_count, 0)            AS char_count,
            COALESCE(sf.word_count, 0)            AS word_count,
            COALESCE(g.whitespace_before, 0)      AS gap_before,
            COALESCE(sp.in_flow_score, 0.5)       AS in_flow_score,
            COALESCE(g.full_width_like, 0)        AS full_width_like,
            COALESCE(g.narrow_width_like, 0)      AS narrow_width_like,
            COALESCE(sm.is_references_marker, 0)  AS is_references_marker,
            COALESCE(sm.is_appendix_marker, 0)    AS is_appendix_marker
        FROM du_blocks b
        LEFT JOIN du_block_typography    t   ON t.block_id  = b.block_id
        LEFT JOIN du_block_surface       sf  ON sf.block_id = b.block_id
        LEFT JOIN du_block_spacing       sp  ON sp.block_id = b.block_id
        LEFT JOIN du_block_geometry      g   ON g.block_id  = b.block_id
        LEFT JOIN du_block_semantic_micro sm ON sm.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()]


def _check_toc(conn: sqlite3.Connection, document_id: str) -> tuple[bool, int]:
    """Check if document has a TOC and determine max TOC level."""
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM du_block_semantic_micro sm
        JOIN du_blocks b ON b.block_id = sm.block_id
        WHERE b.document_id = ? AND sm.is_toc_marker = 1
        """,
        (document_id,),
    ).fetchone()
    # Fallback: check section_tree source for TOC-derived entries
    toc_rows = conn.execute(
        """
        SELECT MAX(level) as max_level FROM du_section_tree
        WHERE document_id = ? AND source LIKE '%toc%'
        """,
        (document_id,),
    ).fetchone()
    has_toc = bool(row and row["cnt"] > 0)
    max_level = _i(toc_rows["max_level"]) if toc_rows else 0
    return has_toc, max_level


# ── Core algorithm ────────────────────────────────────────────────────────────

def _identify_body_font(blocks: list[dict]) -> tuple[float, bool]:
    """Find the dominant font size by weighted character count.

    Returns (body_font_size, body_is_bold).
    The body font is the font used for the most characters overall.
    """
    # Weight by character count — long paragraphs dominate
    size_chars: dict[float, int] = {}
    for b in blocks:
        fs = _f(b.get("font_size"))
        cc = _i(b.get("char_count"))
        if fs > 0 and cc > 0:
            size_chars[fs] = size_chars.get(fs, 0) + cc

    if not size_chars:
        return 10.0, False

    body_font = max(size_chars, key=size_chars.__getitem__)

    # Is the body font typically bold? (unusual but e.g. some textbooks)
    bold_chars = sum(
        _i(b.get("char_count")) for b in blocks
        if abs(_f(b.get("font_size")) - body_font) < 0.5
        and bool(b.get("bold"))
    )
    total_body_chars = size_chars[body_font]
    body_bold = bold_chars > total_body_chars * 0.6

    _log.debug("typography_profile: body_font=%.1fpt bold=%s chars=%d",
               body_font, body_bold, total_body_chars)
    return body_font, body_bold


def _compute_gap_norms(blocks: list[dict],
                       body_font: float) -> tuple[float, float, float]:
    """Compute gap statistics from body-text blocks only.

    Returns (median, p75, p90) of paragraph_gap_before.
    """
    gaps = [
        _f(b.get("gap_before"))
        for b in blocks
        if abs(_f(b.get("font_size")) - body_font) < 1.5
        and _i(b.get("word_count")) >= 8
        and 0 < _f(b.get("gap_before")) < 500
    ]
    if not gaps:
        return 5.0, 10.0, 15.0

    gaps_sorted = sorted(gaps)
    n = len(gaps_sorted)
    median = statistics.median(gaps_sorted)
    p75 = gaps_sorted[int(n * 0.75)]
    p90 = gaps_sorted[int(n * 0.90)]
    return median, p75, p90


def _cluster_font_sizes(blocks: list[dict],
                         body_font: float) -> list[FontClass]:
    """Cluster distinct font sizes into typography classes.

    Strategy:
    1. Compute font_ratio = font_size / body_font for each block
    2. Group font_ratios within 0.05 tolerance
    3. Label clusters: body (~1.0), small (<0.85), h3 (1.05-1.25),
       h2 (1.25-1.60), h1 (>1.60)
    4. Within each size cluster, split by bold/italic if both variants
       have significant character counts

    Returns clusters sorted by font_ratio descending (largest first = h1).
    """
    # Accumulate stats per (font_ratio_bucket, bold) key
    bucket_stats: dict[tuple[float, bool], dict] = {}

    for b in blocks:
        fs = _f(b.get("font_size"))
        cc = _i(b.get("char_count"))
        wc = _i(b.get("word_count"))
        # Skip decorative/graphic elements: tiny char count or extreme font size
        if fs <= 0 or cc < 3 or wc < 1:
            continue
        # Skip blocks with extreme font ratios (>8x body) — graphics, not text
        if fs / body_font > 8.0:
            continue
        ratio = fs / body_font
        # Round to nearest 0.05 bucket
        bucket = round(ratio * 20) / 20
        bold = bool(b.get("bold"))
        key = (bucket, bold)
        if key not in bucket_stats:
            bucket_stats[key] = {"char_count": 0, "block_count": 0,
                                  "all_caps_count": 0}
        bucket_stats[key]["char_count"] += _i(b.get("char_count"))
        bucket_stats[key]["block_count"] += 1
        if bool(b.get("is_all_caps")):
            bucket_stats[key]["all_caps_count"] += 1

    if not bucket_stats:
        return []

    # Build FontClass objects
    total_chars = sum(v["char_count"] for v in bucket_stats.values())
    classes: list[FontClass] = []

    for (ratio_bucket, bold), stats in sorted(bucket_stats.items(),
                                               key=lambda x: -x[0][0]):
        cc = stats["char_count"]
        bc = stats["block_count"]
        if cc == 0:
            continue

        # Determine label
        if 0.85 <= ratio_bucket <= 1.15 and not bold:
            label = "body"
        elif ratio_bucket < 0.85:
            label = "small"
        elif 0.85 <= ratio_bucket <= 1.15 and bold:
            label = "sub_h"    # same size but bold — often L3/L4 in dense docs
        elif ratio_bucket <= 1.25:
            label = "sub_h"    # slightly larger — often L3/L4
        elif ratio_bucket <= 1.60:
            label = "mid_h"    # medium heading — often L2
        else:
            label = "large_h"  # large heading — often L1/title

        is_all_caps = (stats["all_caps_count"] > bc * 0.5)

        fc = FontClass(
            label=label,
            font_ratio_min=ratio_bucket - 0.05,
            font_ratio_max=ratio_bucket + 0.05,
            bold=bold,
            is_all_caps=is_all_caps if stats["all_caps_count"] > 0 else None,
            block_count=bc,
            char_count=cc,
        )
        classes.append(fc)

    # Assign heading levels: largest non-body, non-small classes get L1, L2, ...
    # Body and small classes get heading_level=None
    heading_candidates = [
        fc for fc in classes
        if fc.label not in ("body", "small")
        and fc.char_count > 0
        # Must have significant presence but not dominate document
        # (avoids classifying rare large decorative elements as H1)
        and fc.block_count >= 2
    ]

    # Sort by font_ratio descending, then bold descending
    heading_candidates.sort(
        key=lambda fc: (-(fc.font_ratio_min + fc.font_ratio_max) / 2,
                        -(1 if fc.bold else 0))
    )

    for level, fc in enumerate(heading_candidates, start=1):
        fc.heading_level = level
        _log.debug(
            "typography_profile: L%d → ratio=%.2f-%.2f bold=%s all_caps=%s "
            "blocks=%d label=%s",
            level, fc.font_ratio_min, fc.font_ratio_max,
            fc.bold, fc.is_all_caps, fc.block_count, fc.label,
        )

    return classes


# ── Public API ────────────────────────────────────────────────────────────────

def build_typography_profile(conn: sqlite3.Connection,
                              document_id: str) -> TypographyProfile:
    """Build a TypographyProfile for one document.

    Reads from Layer 1 measurement tables (must be populated first).
    Called after all measure/* steps, before aggregate/signals.py.

    Returns a TypographyProfile with document-relative measurements.
    """
    profile = TypographyProfile(document_id=document_id)

    blocks = _fetch_span_stats(conn, document_id)
    if not blocks:
        _log.warning("typography_profile doc=%s: no blocks found",
                     document_id[:12])
        return profile

    # Step 1: identify body font
    body_font, body_bold = _identify_body_font(blocks)
    profile.body_font = body_font
    profile.body_bold = body_bold

    # Step 2: gap norms from body blocks
    gap_norm, gap_p75, gap_p90 = _compute_gap_norms(blocks, body_font)
    profile.gap_norm = gap_norm
    profile.gap_p75  = gap_p75
    profile.gap_p90  = gap_p90

    # Step 3: font class clustering
    profile.font_classes = _cluster_font_sizes(blocks, body_font)

    # Step 4: TOC detection
    try:
        has_toc, toc_max = _check_toc(conn, document_id)
        profile.has_toc = has_toc
        profile.toc_max_level = toc_max
    except Exception:
        pass  # TOC detection is best-effort

    _log.info(
        "typography_profile doc=%s: body=%.1fpt gap_norm=%.1f "
        "font_classes=%d has_toc=%s",
        document_id[:12], body_font, gap_norm,
        len([fc for fc in profile.font_classes if fc.heading_level]),
        profile.has_toc,
    )

    return profile
