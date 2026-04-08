# src/atlas/understanding/interpret/anchor_detection.py
"""Detect high-confidence heading anchors and derive HeadingPatterns.

This module implements Pass 3.4 of the DU pipeline. It identifies
blocks that are almost certainly headings (anchors), then learns a
HeadingPattern for each level from those anchors.

The key insight: we do not need to classify every block. We only need
to find a handful of unambiguous examples per level, extract their
typographic fingerprint, and apply that fingerprint to the rest.

Two tiers of anchors
--------------------
Tier 1 — high-confidence (all three conditions):
  a) Typography is in a non-body FontClass (per TypographyProfile)
     OR bold at body font size
  b) relative_gap > 1.5  (more whitespace than typical body gap)
  c) in_flow_score < 0.75  (not embedded in running text)

Tier 2 — very high-confidence (Tier 1 + at least one of):
  a) starts_with_number  (e.g. "1.2 Materials", "3.2.1 Dead Loads")
  b) ALL_CAPS at font_ratio > 1.3
  c) TOC match (title appears verbatim in TOC blocks)

HeadingPattern
--------------
From anchors per level, we derive a HeadingPattern:
  - font_ratio range (min/max of anchor ratios ± tolerance)
  - bold (True/False/None = mixed)
  - all_caps (True/False/None = mixed)
  - gap_rel_min: minimum relative gap for pattern application
  - flow_max: maximum in_flow_score
  - number_re: regex if all anchors share a numbering pattern
  - confidence: fraction of Tier-2 among all anchors for this level

Opportunistic
-------------
If no anchors are found → no patterns → empty section tree.
If confidence < 0.3 → only L1 pattern retained.
If confidence ≥ 0.7 → full pattern set applied up to L3.
Deeper levels (L4+) only if numbering pattern is present.
"""
from __future__ import annotations

import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from typing import Any

from atlas.core.logging import get_logger

_log = get_logger("atlas.du.anchor_detection")


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

def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Anchor:
    """A high-confidence heading block."""
    block_id:     str
    block_index:  int
    page_index:   int
    text:         str
    font_ratio:   float          # font_size / body_font
    bold:         bool
    all_caps:     bool
    gap_rel:      float          # whitespace_before / gap_norm
    in_flow:      float
    tier:         int            # 1 or 2
    font_class_level: int | None # heading_level from TypographyProfile


@dataclass
class HeadingPattern:
    """Typographic fingerprint for one heading level.

    Applied in headings.py to classify heading candidates.
    """
    level:          int
    font_ratio_min: float
    font_ratio_max: float
    bold:           bool | None    # None = accept both
    all_caps:       bool | None    # None = accept both
    gap_rel_min:    float          # relative gap minimum
    flow_max:       float          # maximum in_flow_score
    number_re:      str | None     # numbering regex, e.g. r'^\d+\.\d+\s'
    confidence:     float          # 0–1, fraction of Tier-2 anchors
    anchor_count:   int

    def matches(self, font_ratio: float, bold: bool, all_caps: bool,
                gap_rel: float, in_flow: float, text: str) -> bool:
        """Return True if a block matches this pattern."""
        # Typography must be within range
        if not (self.font_ratio_min <= font_ratio <= self.font_ratio_max):
            return False
        # Bold must match (if constrained)
        if self.bold is not None and bold != self.bold:
            return False
        # ALL_CAPS must match (if constrained)
        if self.all_caps is not None and all_caps != self.all_caps:
            return False
        # Must not be embedded in running text
        if in_flow > self.flow_max:
            return False
        # Must have sufficient whitespace (relaxed: 0.5× minimum)
        if gap_rel < self.gap_rel_min * 0.5:
            return False
        # If a numbering pattern exists, it must match (hard constraint)
        if self.number_re and not re.match(self.number_re, text):
            return False
        return True


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_blocks(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    """Fetch all blocks with the signals needed for anchor detection."""
    return [dict(r) for r in conn.execute(
        """
        SELECT
            b.block_id, b.block_index, b.page_index, b.text,
            COALESCE(t.font_size, 0.0)            AS font_size,
            COALESCE(t.bold, 0)                   AS bold,
            COALESCE(t.italic, 0)                 AS italic,
            COALESCE(sf.is_all_caps, 0)           AS is_all_caps,
            COALESCE(sf.starts_with_number, 0)    AS starts_with_number,
            COALESCE(sf.ends_with_colon, 0)       AS ends_with_colon,
            COALESCE(sf.word_count, 0)            AS word_count,
            COALESCE(sf.char_count, 0)            AS char_count,
            COALESCE(g.whitespace_before, 0)      AS whitespace_before,
            COALESCE(sp.in_flow_score, 0.5)       AS in_flow_score,
            COALESCE(sp.paragraph_gap_before, 0)  AS paragraph_gap_before,
            COALESCE(f.running_header_like, 0)    AS running_header_like,
            COALESCE(f.repeated_across_pages, 0)  AS repeated_across_pages,
            COALESCE(g.in_colored_box, 0)          AS in_colored_box,
            COALESCE(sm.is_references_marker, 0)  AS is_references_marker,
            COALESCE(sm.is_appendix_marker, 0)    AS is_appendix_marker,
            COALESCE(z.zone, 'body')              AS zone,
            r.role                                AS role,
            COALESCE(r.heading_score, 0)          AS heading_score,
            COALESCE(r.body_score, 0)             AS body_score
        FROM du_blocks b
        LEFT JOIN du_block_typography    t   ON t.block_id  = b.block_id
        LEFT JOIN du_block_surface       sf  ON sf.block_id = b.block_id
        LEFT JOIN du_block_geometry      g   ON g.block_id  = b.block_id
        LEFT JOIN du_block_spacing       sp  ON sp.block_id = b.block_id
        LEFT JOIN du_block_furniture     f   ON f.block_id  = b.block_id
        LEFT JOIN du_block_semantic_micro sm ON sm.block_id = b.block_id
        LEFT JOIN du_block_zones         z   ON z.block_id  = b.block_id
        LEFT JOIN du_block_roles         r   ON r.block_id  = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()]


def _fetch_toc_titles(conn: sqlite3.Connection, document_id: str) -> set[str]:
    """Fetch normalised titles from TOC blocks (if any)."""
    rows = conn.execute(
        """
        SELECT b.text FROM du_blocks b
        JOIN du_block_zones z ON z.block_id = b.block_id
        WHERE b.document_id = ?
        AND z.zone IN ('front_matter', 'body')
        AND b.text LIKE '%...%'
        LIMIT 200
        """,
        (document_id,),
    ).fetchall()
    titles = set()
    for r in rows:
        # TOC lines look like "1.2 Materials ......... 14"
        # Strip trailing dots and numbers to get the title
        line = _norm(r[0] or "")
        clean = re.sub(r'[.\s]*\d+\s*$', '', line).strip()
        if len(clean) >= 3:
            titles.add(clean.lower())
    return titles


# ── Tier classification ───────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r'^\d+[\.\d]*\s+\S')
_CHAPTER_NUMBER_RE = re.compile(r'^\d+\s+[A-Z]')


def _is_tier2(block: dict, text: str, font_ratio: float,
               all_caps: bool, toc_titles: set[str]) -> bool:
    """Return True if this block qualifies as a Tier-2 anchor."""
    # Explicit numbering: "1.2 Materials", "3.2.1 Dead Loads"
    if bool(block.get("starts_with_number")) and _NUMBER_RE.match(text):
        return True
    # ALL_CAPS at significantly larger font
    if all_caps and font_ratio >= 1.3:
        return True
    # TOC match
    normalized = text.lower()
    if normalized in toc_titles:
        return True
    # Chapter-style: "1 TIMBER CONSTRUCTION"
    if _CHAPTER_NUMBER_RE.match(text) and all_caps:
        return True
    return False


# ── Numbering pattern extraction ──────────────────────────────────────────────

def _extract_number_re(anchors: list[Anchor]) -> str | None:
    """Derive a numbering regex from anchors if consistent.

    Returns a compiled regex string or None if no consistent pattern.
    """
    patterns = {
        r'^\d+\.\d+\.\d+\.\d+\s': 0,   # 1.2.3.4
        r'^\d+\.\d+\.\d+\s':      0,   # 1.2.3
        r'^\d+\.\d+\s':           0,   # 1.2
        r'^\d+\s':                0,   # 1
    }
    for a in anchors:
        for pat in patterns:
            if re.match(pat, a.text):
                patterns[pat] += 1

    # Use the most specific pattern that matches ≥ 60% of anchors
    n = len(anchors)
    for pat in sorted(patterns, key=lambda p: p.count(r'\.')):
        if patterns[pat] >= max(2, n * 0.6):
            return pat
    return None


# ── Pattern building ──────────────────────────────────────────────────────────

_RATIO_TOLERANCE = 0.08   # ±8% around cluster centre
_GAP_TOLERANCE   = 0.30   # relax gap minimum by 30%


def _build_pattern(level: int, anchors: list[Anchor]) -> HeadingPattern | None:
    """Build a HeadingPattern from a list of anchors for one level."""
    if not anchors:
        return None

    ratios   = [a.font_ratio for a in anchors]
    gaps     = [a.gap_rel    for a in anchors]
    flows    = [a.in_flow    for a in anchors]

    # If anchors span a very wide ratio range (>0.4), use only the
    # dominant cluster (most anchors) to avoid an overly broad pattern.
    # This happens when numbered headings at different font sizes share
    # the same numbering depth (e.g. "1.2 Materials" at 10pt and
    # "1 TIMBER CONSTRUCTION" at 18pt both have numbering depth 1).
    total_span = max(ratios) - min(ratios) if len(ratios) > 1 else 0
    if total_span > 0.40:
        ratio_median = statistics.median(ratios)
        anchors = [a for a in anchors
                   if abs(a.font_ratio - ratio_median) <= 0.25]
        if not anchors:
            return None
        ratios = [a.font_ratio for a in anchors]
        gaps   = [a.gap_rel    for a in anchors]
        flows  = [a.in_flow    for a in anchors]

    ratio_center = statistics.median(ratios)
    ratio_spread = (max(ratios) - min(ratios)) / 2 if len(ratios) > 1 else 0.05
    ratio_spread = max(ratio_spread, _RATIO_TOLERANCE)

    bold_votes    = sum(1 for a in anchors if a.bold)
    caps_votes    = sum(1 for a in anchors if a.all_caps)
    n             = len(anchors)
    tier2_count   = sum(1 for a in anchors if a.tier == 2)
    confidence    = tier2_count / n

    bold     = True  if bold_votes    >= n * 0.75 else \
               False if bold_votes    <= n * 0.25 else None
    all_caps = True  if caps_votes    >= n * 0.75 else \
               False if caps_votes    <= n * 0.25 else None

    gap_rel_min  = max(0.3, statistics.median(gaps) * (1 - _GAP_TOLERANCE))
    flow_max     = min(0.90, max(flows) + 0.10)

    number_re = _extract_number_re(anchors)

    _log.debug(
        "anchor_detection: L%d pattern: ratio=%.2f±%.2f bold=%s "
        "all_caps=%s gap_min=%.2f flow_max=%.2f number_re=%s "
        "anchors=%d confidence=%.2f",
        level, ratio_center, ratio_spread, bold, all_caps,
        gap_rel_min, flow_max, number_re, n, confidence,
    )

    return HeadingPattern(
        level=level,
        font_ratio_min=ratio_center - ratio_spread,
        font_ratio_max=ratio_center + ratio_spread,
        bold=bold,
        all_caps=all_caps,
        gap_rel_min=gap_rel_min,
        flow_max=flow_max,
        number_re=number_re,
        confidence=confidence,
        anchor_count=n,
    )


# ── Level assignment for anchors ──────────────────────────────────────────────

def _assign_levels(anchors: list[Anchor]) -> dict[int, list[Anchor]]:
    """Group anchors by their likely heading level.

    Strategy:
    1. Anchors with font_class_level use that level directly.
    2. Remaining anchors are clustered by font_ratio into levels.
    3. Numbering depth overrides font-based level if available.
    """
    by_level: dict[int, list[Anchor]] = {}

    # Pass 1: use font_class_level where available
    unassigned = []
    for a in anchors:
        if a.font_class_level is not None:
            by_level.setdefault(a.font_class_level, []).append(a)
        else:
            unassigned.append(a)

    # Pass 2: cluster unassigned by font_ratio
    if unassigned:
        unassigned.sort(key=lambda a: -a.font_ratio)
        next_level = max(by_level.keys(), default=0) + 1
        last_ratio = None
        current_level = next_level
        for a in unassigned:
            if last_ratio is None or abs(a.font_ratio - last_ratio) > 0.12:
                current_level = next_level
                next_level += 1
            by_level.setdefault(current_level, []).append(a)
            last_ratio = a.font_ratio

    # Pass 3: override level with numbering depth for numbered anchors
    # "1.2.3 Title" → L3, regardless of font
    final: dict[int, list[Anchor]] = {}
    for level, level_anchors in by_level.items():
        for a in level_anchors:
            num_level = _numbering_depth(a.text)
            effective_level = num_level if num_level else level
            final.setdefault(effective_level, []).append(a)

    # Pass 4: re-number levels starting at 1
    # Only for unnumbered documents — numbered documents encode
    # level in their numbering depth (1.2.3 = L3) and must not
    # be renumbered.
    has_numbering = any(_numbering_depth(a.text) for a in anchors)
    if not has_numbering and final:
        sorted_levels = sorted(final.keys())
        if sorted_levels[0] != 1:
            offset = sorted_levels[0] - 1
            final = {lvl - offset: alist
                     for lvl, alist in final.items()}
    return final


def _numbering_depth(text: str) -> int | None:
    """Return heading level from numbering prefix, or None."""
    m = re.match(r'^(\d+)((?:\.\d+)*)\s', text)
    if not m:
        return None
    dots = m.group(2)
    return 1 + dots.count('.')


# ── Noise gates ───────────────────────────────────────────────────────────────

def _is_furniture(block: dict) -> bool:
    """True for running headers, footers, page numbers."""
    return (bool(block.get("running_header_like"))
            or bool(block.get("repeated_across_pages")))


def _is_backmatter_label(block: dict, text: str) -> bool:
    """True for reference/appendix markers that are not real headings."""
    if bool(block.get("is_references_marker")) or bool(block.get("is_appendix_marker")):
        # Only exclude if very short — "References" alone is a valid L1
        return len(text.split()) <= 1
    return False


def _is_formula_or_caption(block: dict, text: str) -> bool:
    """True for formula steps and figure/table captions."""
    # Ends with colon and embedded in text
    if bool(block.get("ends_with_colon")) and _f(block.get("in_flow_score")) > 0.70:
        return True
    # EXAMPLE N.N-N, Table N.N-N, Figure N.N-N
    if re.match(r'^(?:example|table|figure|fig\.?|tab\.?)\s+[\d]', text,
                re.IGNORECASE):
        return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def detect_anchors(
    conn: sqlite3.Connection,
    document_id: str,
    typography_profile: "TypographyProfile | None" = None,
) -> list[HeadingPattern]:
    """Detect high-confidence heading anchors and derive HeadingPatterns.

    Parameters
    ----------
    conn : sqlite3.Connection
    document_id : str
    typography_profile : TypographyProfile, optional
        If provided, used for font_ratio and relative_gap calculation.
        If None, falls back to raw font_size and gap heuristics.

    Returns
    -------
    list[HeadingPattern]
        One pattern per detected heading level, sorted by level.
        Empty list if no high-confidence anchors found.
    """
    from atlas.understanding.measure.typography_profile import (
        TypographyProfile, build_typography_profile,
    )

    if typography_profile is None:
        typography_profile = build_typography_profile(conn, document_id)

    tp = typography_profile
    body_font  = tp.body_font  if tp.body_font > 0  else 10.0
    gap_norm   = tp.gap_norm   if tp.gap_norm > 0   else 5.0
    flow_threshold = tp.flow_threshold

    blocks     = _fetch_blocks(conn, document_id)
    toc_titles = _fetch_toc_titles(conn, document_id)

    if not blocks:
        _log.warning("anchor_detection doc=%s: no blocks", document_id[:12])
        return []

    # ── Collect anchors ───────────────────────────────────────────────────────
    anchors: list[Anchor] = []

    for b in blocks:
        # Skip furniture
        if _is_furniture(b):
            continue

        text = _norm(b.get("text"))
        if not text or len(text) < 2:
            continue

        fs         = _f(b.get("font_size"))
        bold       = bool(b.get("bold"))
        all_caps   = bool(b.get("is_all_caps"))
        ws_before  = _f(b.get("whitespace_before"))
        in_flow    = _f(b.get("in_flow_score"), 0.5)
        wc         = _i(b.get("word_count"))

        if fs <= 0:
            continue

        font_ratio = fs / body_font
        gap_rel    = ws_before / gap_norm if gap_norm > 0 else 1.0

        # Skip formula/caption blocks regardless of typography
        if _is_formula_or_caption(b, text):
            continue

        # Skip blocks inside colored boxes (maps, decorative frames)
        # in_colored_box = True means the block is inside a colored
        # rectangle — these are never headings (map labels, callouts)
        if bool(b.get("in_colored_box")):
            continue

        # Skip image captions: italic + near image + starts with number
        italic = bool(b.get("italic"))
        near_img = _f(b.get("near_image_score"))
        if italic and near_img > 0.3:
            continue
        # Skip caption numbers: starts_with_number but font clearly smaller
        # italic + starts_with_number + font <= body → caption
        # (e.g. "6 Diele eines..." without near_image_score)
        if italic and bool(b.get("starts_with_number")) and font_ratio <= 1.05:
            continue
        # than body (ratio < 0.92). Avoids filtering headings that are
        # marginally smaller than body_font (e.g. 10.0pt vs body 10.2pt).
        if bool(b.get("starts_with_number")) and font_ratio < 0.92:
            continue

        # Skip very long blocks (body text, not headings)
        if wc > 20:
            continue

        # Skip single tokens that are likely noise:
        # - Pure numbers (page numbers: "11", "13")
        # - Very short single words (map labels: "Nordsee", "Polen")
        #   unless they are ALL_CAPS with large font (chapter titles)
        if wc == 1:
            if text.isdigit():
                continue
            if len(text) <= 8 and not all_caps and font_ratio < 1.4:
                continue

        # ── Tier 1: is this block in a heading font class? ────────────────────
        in_heading_class = False
        fc_level = None

        for fc in tp.font_classes:
            if fc.heading_level is None:
                continue
            if (fc.font_ratio_min <= font_ratio <= fc.font_ratio_max
                    and (fc.bold is None or fc.bold == bold)):
                in_heading_class = True
                fc_level = fc.heading_level
                break

        # Also accept bold at body size as a heading class
        if not in_heading_class and bold and 0.88 <= font_ratio <= 1.12:
            in_heading_class = True
            fc_level = None  # will be assigned later

        if not in_heading_class:
            continue

        # Tier 1 gate — primäre Signale
        # gap_rel ist KEIN Gate: Abstände variieren durch Layout-Engine
        # (Seitenende, Bilder, Spaltenumbrüche, LaTeX-Ausgleich).
        # Primäres Gate-Signal: in_flow_score.
        if in_flow >= 0.85:
            continue

        # gap_rel als Tier-2-Verstärker (nicht als Ausschluss)
        gap_boost = gap_rel >= 1.5
        tier2 = _is_tier2(b, text, font_ratio, all_caps, toc_titles)
        tier = 2 if (tier2 or (gap_boost and bold and font_ratio >= 0.9)) else 1

        anchors.append(Anchor(
            block_id=b["block_id"],
            block_index=_i(b.get("block_index")),
            page_index=_i(b.get("page_index")),
            text=text,
            font_ratio=font_ratio,
            bold=bold,
            all_caps=all_caps,
            gap_rel=gap_rel,
            in_flow=in_flow,
            tier=tier,
            font_class_level=fc_level,
        ))

    _log.info(
        "anchor_detection doc=%s: %d anchors (tier1=%d tier2=%d)",
        document_id[:12], len(anchors),
        sum(1 for a in anchors if a.tier == 1),
        sum(1 for a in anchors if a.tier == 2),
    )

    if not anchors:
        return []

    # Density gate: if anchors are too dense (>3 per page), this
    # is likely a glossary, index, or list — not a structured text.
    # Return empty patterns so the section tree stays empty.
    page_count = conn.execute(
        "SELECT COUNT(DISTINCT page_index) FROM du_blocks WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0] or 1
    anchor_density = len(anchors) / page_count
    if anchor_density > 3.0:
        _log.info(
            "anchor_detection doc=%s: density=%.1f anchors/page > 3.0 "
            "— likely glossary/index, skipping patterns",
            document_id[:12], anchor_density,
        )
        return []

    # ── Assign levels and build patterns ──────────────────────────────────────
    by_level = _assign_levels(anchors)

    patterns: list[HeadingPattern] = []
    overall_confidence = (
        sum(1 for a in anchors if a.tier == 2) / len(anchors)
    )

    for level, level_anchors in sorted(by_level.items()):
        pattern = _build_pattern(level, level_anchors)
        if pattern is None:
            continue

        # Opportunistic gates:
        # - L4+ only if explicit numbering pattern found
        if level >= 4 and pattern.number_re is None:
            _log.debug(
                "anchor_detection: L%d dropped — no numbering pattern",
                level,
            )
            continue

        # - Low overall confidence → only L1, unless anchors are
        # consistent (small ratio spread = same font used throughout)
        if overall_confidence < 0.3 and level > 1:
            ratios = [a.font_ratio for a in level_anchors]
            spread = (max(ratios) - min(ratios)) if len(ratios) > 1 else 0
            if spread > 0.15 or len(level_anchors) < 2:
                _log.debug(
                    "anchor_detection: L%d dropped — low confidence "
                    "(%.2f) and inconsistent (spread=%.2f n=%d)",
                    level, overall_confidence, spread, len(level_anchors),
                )
                continue
            _log.debug(
                "anchor_detection: L%d kept despite low confidence "
                "(%.2f) — consistent anchors (spread=%.2f n=%d)",
                level, overall_confidence, spread, len(level_anchors),
            )

        patterns.append(pattern)

    _log.info(
        "anchor_detection doc=%s: %d patterns (confidence=%.2f)",
        document_id[:12], len(patterns), overall_confidence,
    )

    return sorted(patterns, key=lambda p: p.level)


def persist_patterns(
    conn: sqlite3.Connection,
    document_id: str,
    patterns: list[HeadingPattern],
) -> None:
    """Write HeadingPatterns to du_heading_patterns table.

    Idempotent — deletes existing patterns first.
    """
    conn.execute(
        "DELETE FROM du_heading_patterns WHERE document_id = ?",
        (document_id,),
    )
    if patterns:
        conn.executemany(
            """
            INSERT INTO du_heading_patterns (
                document_id, level, font_ratio_min, font_ratio_max,
                bold, all_caps, gap_rel_min, flow_max,
                number_re, confidence, anchor_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [(document_id, p.level, p.font_ratio_min, p.font_ratio_max,
              (1 if p.bold else 0) if p.bold is not None else None,
              (1 if p.all_caps else 0) if p.all_caps is not None else None,
              p.gap_rel_min, p.flow_max, p.number_re,
              p.confidence, p.anchor_count)
             for p in patterns],
        )
    conn.commit()


def load_patterns(
    conn: sqlite3.Connection,
    document_id: str,
) -> list[HeadingPattern]:
    """Load HeadingPatterns from du_heading_patterns table."""
    rows = conn.execute(
        """
        SELECT level, font_ratio_min, font_ratio_max, bold, all_caps,
               gap_rel_min, flow_max, number_re, confidence, anchor_count
        FROM du_heading_patterns
        WHERE document_id = ?
        ORDER BY level
        """,
        (document_id,),
    ).fetchall()

    def _bool_or_none(v: Any) -> bool | None:
        if v is None:
            return None
        return bool(v)

    return [
        HeadingPattern(
            level=r["level"],
            font_ratio_min=_f(r["font_ratio_min"]),
            font_ratio_max=_f(r["font_ratio_max"]),
            bold=_bool_or_none(r["bold"]),
            all_caps=_bool_or_none(r["all_caps"]),
            gap_rel_min=_f(r["gap_rel_min"]),
            flow_max=_f(r["flow_max"]),
            number_re=r["number_re"],
            confidence=_f(r["confidence"]),
            anchor_count=_i(r["anchor_count"]),
        )
        for r in rows
    ]
