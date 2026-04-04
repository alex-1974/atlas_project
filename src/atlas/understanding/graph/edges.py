# src/atlas/understanding/graph/edges.py
"""Edge types and attributes for the neighbourhood graph.

Edge types
----------
sequential  — Block i → Block i+1 in reading order (always present)
spatial     — Blocks with similar x0 on the same page (column detection)
cross_page  — Last block on page N → first block on page N+1

For Phase 1 only sequential edges are built.
Spatial and cross_page edges are planned for Phase 2.

Edge attributes
---------------
All numeric attributes are normalised to [0, 1] or ratios where possible
so that correction rules can use simple threshold comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


EdgeType = Literal["sequential", "spatial", "cross_page"]


@dataclass
class Edge:
    """Directed edge from block source_idx to block target_idx."""

    source_idx: int          # block_index of the source block
    target_idx: int          # block_index of the target block
    edge_type: EdgeType

    # ── Geometric attributes ──────────────────────────────────────────────────
    # Vertical gap between bottom of source and top of target,
    # normalised by the median inter-block gap of the document.
    # < 1.0 = tighter than median, > 1.0 = looser than median
    vertical_gap_ratio: float = 0.0

    # True if both blocks are on the same page
    same_page: bool = True

    # ── Typographic attributes ────────────────────────────────────────────────
    # font_size(target) / font_size(source).
    # ~1.0 = same size, < 1.0 = target smaller, > 1.0 = target larger
    font_ratio: float = 1.0

    # True if both blocks share the same dominant font family
    same_font_family: bool = True

    # ── Textual attributes ────────────────────────────────────────────────────
    # True if the source block text ends syntactically open:
    # trailing preposition, conjunction, or no sentence-ending punctuation
    # combined with short word count (suggests continuation)
    source_text_continues: bool = False

    # True if the target block text starts with a lowercase letter
    # (strong continuation signal — rare in headings)
    target_starts_lower: bool = False


def _text_continues(text: str) -> bool:
    """Return True if text ends syntactically open (likely continues)."""
    if not text:
        return False
    t = text.strip()
    # Ends with preposition or conjunction (DE + EN)
    _OPEN_ENDINGS = (
        # German
        " im", " in", " an", " auf", " bei", " mit", " von", " zu",
        " und", " oder", " der", " die", " das", " des", " dem", " den",
        " für", " über", " unter", " nach", " vor", " zwischen",
        # English
        " in", " on", " at", " of", " the", " a", " an", " and", " or",
        " to", " for", " with", " by", " from", " between",
    )
    last_word = t.split()[-1].lower() if t.split() else ""
    if any(t.lower().endswith(e) for e in _OPEN_ENDINGS):
        return True
    # Short text (≤ 8 words) that doesn't end with sentence-ending punctuation
    words = t.split()
    if len(words) <= 8 and not t.endswith((".", "!", "?", ":", ";")):
        return True
    return False


def build_sequential_edges(
    blocks: list[dict],
    median_gap: float,
) -> list[Edge]:
    """Build sequential edges between consecutive blocks.

    Parameters
    ----------
    blocks:
        List of block dicts, each containing at minimum:
        block_index, page_index, text, font_size, font_family_normalized,
        whitespace_after (from du_block_geometry or du_block_spacing)
    median_gap:
        Median inter-block vertical gap for the document, used to
        normalise vertical_gap_ratio.
    """
    edges: list[Edge] = []

    for i in range(len(blocks) - 1):
        src = blocks[i]
        tgt = blocks[i + 1]

        raw_gap = float(src.get("whitespace_after") or 0.0)
        gap_ratio = raw_gap / median_gap if median_gap > 0 else 1.0

        src_font = float(src.get("font_size") or 0.0)
        tgt_font = float(tgt.get("font_size") or 0.0)
        font_ratio = (tgt_font / src_font) if src_font > 0 else 1.0

        same_family = (
            src.get("font_family_normalized") ==
            tgt.get("font_family_normalized")
        )

        src_text = (src.get("text") or "").strip()
        tgt_text = (tgt.get("text") or "").strip()

        edge = Edge(
            source_idx=src["block_index"],
            target_idx=tgt["block_index"],
            edge_type="sequential",
            vertical_gap_ratio=round(gap_ratio, 3),
            same_page=(src["page_index"] == tgt["page_index"]),
            font_ratio=round(font_ratio, 3),
            same_font_family=same_family,
            source_text_continues=_text_continues(src_text),
            target_starts_lower=bool(tgt_text and tgt_text[0].islower()),
        )
        edges.append(edge)

    return edges
