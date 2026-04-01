# src/atlas/understanding/measure/typography.py
"""Layer 1 — typographic measurements per block.

Joins du_layout_spans onto du_blocks via bounding-box intersection.
The dominant span (longest text span) determines the block's font
attributes. Writes du_block_typography.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict

# Letter-spacing pattern (Fall B): single characters or short clusters
# separated by spaces. Matches "T H E P A T T E R N", "B U R G A G E".
# Requires ≥ 4 spaced tokens to avoid false positives on initials ("A. B.").
_LETTER_SPACED_RE = re.compile(
    r'^(?:[A-Za-z\u00C0-\u00FF]{1,3}\s+){3,}[A-Za-z\u00C0-\u00FF]{1,3}\s*$'
)


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_blocks(conn: sqlite3.Connection,
                  document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT block_id, page_index, block_index, x0, y0, x1, y1, text
        FROM du_blocks
        WHERE document_id = ?
        ORDER BY block_index
        """,
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_spans(conn: sqlite3.Connection,
                 document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT page_index, x0, y0, x1, y1, text,
               font_name, font_size, font_flags, is_bold, is_italic,
               COALESCE(color, 0) AS color,
               COALESCE(char_spacing, 0.0) AS char_spacing
        FROM du_layout_spans
        WHERE document_id = ?
        ORDER BY page_index, reading_order
        """,
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _intersects(block: dict, span: dict, tol: float = 1.0) -> bool:
    if int(block["page_index"]) != int(span["page_index"]):
        return False
    if any(v is None for v in (
        block["x0"], block["y0"], block["x1"], block["y1"],
        span["x0"],  span["y0"],  span["x1"],  span["y1"],
    )):
        return False
    return not (
        float(span["x1"]) < float(block["x0"]) - tol
        or float(span["x0"]) > float(block["x1"]) + tol
        or float(span["y1"]) < float(block["y0"]) - tol
        or float(span["y0"]) > float(block["y1"]) + tol
    )


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _normalize_font_family(font_name: str | None) -> str | None:
    if not isinstance(font_name, str) or not font_name:
        return font_name
    # Strip subset prefix (e.g. "ABCDEF+TimesNewRoman" → "TimesNewRoman")
    return font_name.split("+")[-1].split(",")[0]


# ── Computation ───────────────────────────────────────────────────────────────

def compute_typography(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute typographic features for every block of one document.

    Writes du_block_typography. Idempotent via INSERT OR REPLACE.
    """
    blocks = _fetch_blocks(conn, document_id)
    spans  = _fetch_spans(conn, document_id)
    if not blocks:
        return

    spans_by_page: dict[int, list[dict]] = defaultdict(list)
    for s in spans:
        spans_by_page[int(s["page_index"])].append(s)

    # Maximum font size per page (for largest_on_page flag).
    page_max_font: dict[int, float | None] = {}
    for pi, page_spans in spans_by_page.items():
        sizes = [float(s["font_size"]) for s in page_spans if s["font_size"] is not None]
        page_max_font[pi] = max(sizes) if sizes else None

    # First pass: collect per-block font attributes.
    temp: list[dict] = []
    for block in blocks:
        page_spans = spans_by_page.get(int(block["page_index"]), [])
        covered    = [s for s in page_spans if _intersects(block, s)]

        if covered:
            dominant = max(covered, key=lambda s: len((s["text"] or "").strip()))
            font_name = dominant.get("font_name")
            font_size = float(dominant["font_size"]) if dominant.get("font_size") is not None else None
            bold      = any(bool(s.get("is_bold"))   for s in covered)
            italic    = any(bool(s.get("is_italic"))  for s in covered)
            # is_serif: majority of covered spans use a serifed font (flags & 4).
            # Sans-serif headings are a strong differentiator in many documents.
            serif_votes = sum(1 for s in covered if int(s.get("font_flags") or 0) & 4)
            is_serif = serif_votes > len(covered) / 2
            # is_letter_spaced (Fall A): dominant span has char_spacing > 0.85.
            # Threshold 0.85 means mean gap ≈ font_size — one full character
            # width between each character, typical of deliberate letter-spacing.
            dom_char_spacing = float(dominant.get("char_spacing") or 0.0)
            is_letter_spaced_a = dom_char_spacing > 0.85
            total_chars    = sum(len((s.get("text") or "").strip()) for s in covered)
            dominant_chars = len((dominant.get("text") or "").strip())
            dominant_font_share = dominant_chars / total_chars if total_chars > 0 else None
            # color_text: the color of the dominant (longest) text span.
            # We use the DOMINANT span's color, not "any span with color".
            # This prevents a single bullet glyph (●, ■, \x84) from tainting
            # the entire block's color — the bullet is never the dominant span
            # because it has fewer characters than the actual text.
            dom_color = int(dominant.get("color") or 0)
            color_text = dom_color if dom_color not in (0, 0xFFFFFF) else 0
        else:
            font_name = font_size = None
            bold = italic = False
            is_serif = False
            is_letter_spaced_a = False
            dominant_font_share = None
            color_text = 0

        text     = block.get("text") or ""
        all_caps = bool(text and text.isupper())
        small_caps = bool(
            not all_caps
            and font_size is not None
            and _caps_ratio(text) > 0.55
        )
        # is_letter_spaced: Fall A (char_spacing from spans) OR
        # Fall B (text pattern "T H E ...").
        is_letter_spaced = (
            is_letter_spaced_a
            or bool(_LETTER_SPACED_RE.match(text.strip()))
        )

        page_max = page_max_font.get(int(block["page_index"]))
        largest_on_page = bool(
            font_size is not None
            and page_max is not None
            and font_size >= page_max - 0.01
        )

        temp.append({
            "block_id":             block["block_id"],
            "font_name":            font_name,
            "font_family":          font_name.split(",")[0] if isinstance(font_name, str) else font_name,
            "font_family_normalized": _normalize_font_family(font_name),
            "font_size":            font_size,
            "bold":                 bold,
            "italic":               italic,
            "is_serif":             is_serif,
            "is_letter_spaced":     is_letter_spaced,
            "is_letter_spaced_a":   is_letter_spaced_a,
            "small_caps":           small_caps,
            "all_caps":             all_caps,
            "largest_on_page":      largest_on_page,
            "dominant_font_share":  dominant_font_share,
            "color_text":           color_text,
        })

    # Document-wide font distribution.
    all_sizes = [r["font_size"] for r in temp if r["font_size"] is not None]
    sorted_sizes = sorted(all_sizes)
    n = len(sorted_sizes)
    doc_mode  = sorted_sizes[n // 2] if all_sizes else None

    def _percentile(fs: float | None) -> float | None:
        """Rank of fs in the document-wide font distribution, in [0, 1].

        Counts the fraction of blocks whose font_size is strictly smaller.
        Two blocks with identical font_size get the same percentile.
        Returns None when fs is unknown.
        """
        if fs is None or not sorted_sizes:
            return None
        smaller = sum(1 for s in sorted_sizes if s < fs)
        return smaller / n

    # Document-wide color analysis.
    #
    # Uses CIEDE2000 perceptual color distance for clustering:
    # - Colors with ΔE < 8.0 are perceptually similar and grouped together.
    # - The largest cluster = body color (color_rank=0).
    # - Non-body clusters with share ≥ 5% AND clearly chromatic (not grey)
    #   get color_rank=1 (structural heading color).
    # - Everything else = color_rank=2 (accent / link / decoration).
    from collections import Counter

    def _rgb_to_lab(c: int) -> tuple[float, float, float]:
        """Convert 0xRRGGBB integer to CIELAB (D65 illuminant)."""
        r = ((c >> 16) & 0xFF) / 255.0
        g = ((c >>  8) & 0xFF) / 255.0
        b = ( c        & 0xFF) / 255.0
        # sRGB linearisation
        def lin(v: float) -> float:
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = lin(r), lin(g), lin(b)
        # sRGB → XYZ (D65)
        X = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
        Y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
        Z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
        # XYZ → Lab
        def f(t: float) -> float:
            return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
        fx, fy, fz = f(X / 0.95047), f(Y), f(Z / 1.08883)
        L = 116 * fy - 16
        a = 500 * (fx - fy)
        b_ = 200 * (fy - fz)
        return L, a, b_

    def _delta_e_approx(c1: int, c2: int) -> float:
        """Fast approximate CIEDE2000-like distance using CIELab Euclidean.
        
        Full CIEDE2000 is complex; CIELab Euclidean (ΔE76) is adequate for
        our clustering purpose: ΔE < 8 = perceptually similar.
        """
        L1, a1, b1 = _rgb_to_lab(c1)
        L2, a2, b2 = _rgb_to_lab(c2)
        return ((L1-L2)**2 + (a1-a2)**2 + (b1-b2)**2) ** 0.5

    def _is_chromatic(c: int) -> bool:
        """True if the color has meaningful hue/saturation (not grey/black/white)."""
        L, a, b_ = _rgb_to_lab(c)
        chroma = (a**2 + b_**2) ** 0.5
        # Chroma > 15 in Lab space = clearly non-grey
        return chroma > 15.0

    raw_counts: Counter = Counter(r["color_text"] for r in temp)
    total_blocks = len(temp)

    # Cluster perceptually similar colors (ΔE < 12.0)
    # Threshold 12.0 clusters CMYK near-black variants (#000000, #1d1d1b)
    # while keeping clearly different colors (greens, blues, greys) separate.
    clusters: list[tuple[int, int]] = []  # (representative, count)
    for color, count in sorted(raw_counts.items(), key=lambda x: -x[1]):
        merged = False
        for i, (rep, c_count) in enumerate(clusters):
            if _delta_e_approx(color, rep) < 12.0:
                clusters[i] = (rep, c_count + count)
                merged = True
                break
        if not merged:
            clusters.append((color, count))

    # Body cluster = largest (most blocks use body color)
    clusters.sort(key=lambda x: -x[1])
    body_rep = clusters[0][0] if clusters else 0

    # Structural colors: non-body clusters with ≥5% share AND chromatic
    structural_reps: set[int] = set()
    for rep, count in clusters[1:]:
        share = count / total_blocks if total_blocks > 0 else 0
        if share >= 0.05 and _is_chromatic(rep):
            structural_reps.add(rep)

    # Map each raw color to its cluster rank
    color_rank_map: dict[int, int] = {}
    for color in raw_counts:
        best_rep = body_rep
        best_dist = _delta_e_approx(color, body_rep)
        for rep, _ in clusters:
            d = _delta_e_approx(color, rep)
            if d < best_dist:
                best_dist = d
                best_rep = rep
        if best_rep == body_rep or _delta_e_approx(color, body_rep) < 12.0:
            color_rank_map[color] = 0  # body
        elif best_rep in structural_reps:
            color_rank_map[color] = 1  # structural heading color
        else:
            color_rank_map[color] = 2  # accent / link / decoration

    # Second pass: add relative / delta features that need doc_mode and neighbours.
    rows: list[tuple] = []
    for i, row in enumerate(temp):
        prev = temp[i - 1] if i > 0 else None
        nxt  = temp[i + 1] if i + 1 < len(temp) else None

        fs      = row["font_size"]
        fs_prev = prev["font_size"] if prev else None
        fs_next = nxt["font_size"]  if nxt  else None

        font_ratio         = (fs / doc_mode) if fs is not None and doc_mode else None
        font_pct           = _percentile(fs)
        delta_prev         = (fs - fs_prev)  if fs is not None and fs_prev is not None else None
        delta_next         = (fs - fs_next)  if fs is not None and fs_next is not None else None
        larger_than_prev   = int(delta_prev is not None and delta_prev > 0.1)
        larger_than_next   = int(delta_next is not None and delta_next > 0.1)
        is_doc_font_mode   = int(fs is not None and doc_mode is not None
                                  and abs(fs - doc_mode) < 0.1)

        rows.append((
            row["block_id"],
            row["font_name"],
            row["font_family"],
            row["font_family_normalized"],
            fs,
            font_ratio,
            font_pct,
            int(row["bold"]),
            int(row["italic"]),
            int(row["is_serif"]),
            int(row["is_letter_spaced"]),
            int(row["small_caps"]),
            int(row["all_caps"]),
            int(row["largest_on_page"]),
            larger_than_prev,
            larger_than_next,
            is_doc_font_mode,
            row["dominant_font_share"],
            delta_prev,
            delta_next,
            row["color_text"],
            color_rank_map.get(row["color_text"], 0),
        ))

    conn.executemany(
        """
        INSERT INTO du_block_typography (
            block_id,
            font_name, font_family, font_family_normalized,
            font_size, font_ratio, font_percentile,
            bold, italic, is_serif, is_letter_spaced, small_caps, all_caps,
            largest_on_page, larger_than_prev, larger_than_next,
            is_document_font_mode, dominant_font_share,
            font_size_delta_prev, font_size_delta_next,
            text_color, color_rank
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            font_name              = excluded.font_name,
            font_family            = excluded.font_family,
            font_family_normalized = excluded.font_family_normalized,
            font_size              = excluded.font_size,
            font_ratio             = excluded.font_ratio,
            font_percentile        = excluded.font_percentile,
            bold                   = excluded.bold,
            italic                 = excluded.italic,
            is_serif               = excluded.is_serif,
            is_letter_spaced       = excluded.is_letter_spaced,
            small_caps             = excluded.small_caps,
            all_caps               = excluded.all_caps,
            largest_on_page        = excluded.largest_on_page,
            larger_than_prev       = excluded.larger_than_prev,
            larger_than_next       = excluded.larger_than_next,
            is_document_font_mode  = excluded.is_document_font_mode,
            dominant_font_share    = excluded.dominant_font_share,
            font_size_delta_prev   = excluded.font_size_delta_prev,
            font_size_delta_next   = excluded.font_size_delta_next,
            text_color             = excluded.text_color,
            color_rank             = excluded.color_rank
        """,
        rows,
    )
    conn.commit()
