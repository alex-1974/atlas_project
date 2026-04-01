# src/atlas/understanding/measure/geometry.py
"""Layer 1 — spatial measurements per block.

Reads du_blocks and du_pages, writes du_block_geometry.
Also back-fills doc_y0 / doc_y1 in du_blocks — the only permitted
cross-table write from a Layer 1 module (these are geometric coordinates,
not role or signal data).

column_hint is intentionally absent from the schema until column
detection is implemented (OE-1, Phase 4).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_pages(conn: sqlite3.Connection,
                 document_id: str) -> dict[int, dict]:
    rows = conn.execute(
        """
        SELECT page_index, width, height
        FROM du_pages
        WHERE document_id = ?
        ORDER BY page_index
        """,
        (document_id,),
    ).fetchall()
    return {int(r["page_index"]): {"width": r["width"], "height": r["height"]}
            for r in rows}


def _fetch_blocks(conn: sqlite3.Connection,
                  document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT block_id, page_index, block_index, x0, y0, x1, y1
        FROM du_blocks
        WHERE document_id = ?
        ORDER BY page_index, block_index
        """,
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Pure geometry helpers ─────────────────────────────────────────────────────

def _median(values: list) -> float | None:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    return clean[len(clean) // 2]


def _safe_ratio(value: float | None, denom: float | None) -> float | None:
    if value is None or not denom:
        return None
    return float(value) / float(denom)


def _fetch_images(conn: sqlite3.Connection,
                  document_id: str) -> dict[int, list[dict]]:
    """Return image bounding boxes grouped by page_index.

    Excludes full-page images (≥70% of page area) — these are scanned pages,
    not illustrations next to text.  For such documents near_image_score would
    fire on every block, making it meaningless.
    """
    try:
        rows = conn.execute(
            """
            SELECT i.page_index, i.x0, i.y0, i.x1, i.y1,
                   p.width AS pw, p.height AS ph
            FROM du_layout_images i
            JOIN du_pages p ON p.document_id = i.document_id
                            AND p.page_index = i.page_index
            WHERE i.document_id = ?
            """,
            (document_id,),
        ).fetchall()
    except Exception:
        return {}
    by_page: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        pw = float(r["pw"] or 1.0)
        ph = float(r["ph"] or 1.0)
        page_area = pw * ph
        img_area  = (float(r["x1"]) - float(r["x0"])) * (float(r["y1"]) - float(r["y0"]))
        if page_area > 0 and img_area / page_area >= 0.70:
            continue  # full-page scan — skip
        by_page[int(r["page_index"])].append({
            "x0": float(r["x0"]), "y0": float(r["y0"]),
            "x1": float(r["x1"]), "y1": float(r["y1"]),
        })
    return dict(by_page)


def _min_distance_to_images(bx0: float, by0: float, bx1: float, by1: float,
                              images: list[dict]) -> float:
    """Minimum gap (pt) between a text block and any image on the same page.

    Returns a large number (9999) if there are no images on the page.
    Negative values mean overlap — treated as distance 0.
    """
    if not images:
        return 9999.0
    min_d = 9999.0
    for img in images:
        # Horizontal and vertical gap between the two rectangles
        h_gap = max(0.0, max(bx0, img["x0"]) - min(bx1, img["x1"]))
        v_gap = max(0.0, max(by0, img["y0"]) - min(by1, img["y1"]))
        d = (h_gap ** 2 + v_gap ** 2) ** 0.5
        if d < min_d:
            min_d = d
    return min_d



def _fetch_drawings(conn: sqlite3.Connection,
                    document_id: str) -> dict[int, list[dict]]:
    """Return colored background fills grouped by page_index."""
    try:
        rows = conn.execute(
            """
            SELECT page_index, x0, y0, x1, y1, fill_r, fill_g, fill_b
            FROM du_layout_drawings
            WHERE document_id = ?
            """,
            (document_id,),
        ).fetchall()
    except Exception:
        return {}
    by_page: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_page[int(r["page_index"])].append({
            "x0": float(r["x0"]), "y0": float(r["y0"]),
            "x1": float(r["x1"]), "y1": float(r["y1"]),
        })
    return dict(by_page)


def _block_in_drawing(bx0: float, by0: float, bx1: float, by1: float,
                       drawings: list[dict],
                       overlap_threshold: float = 0.60) -> bool:
    """Return True if the block's area overlaps a colored box by at least
    `overlap_threshold` fraction."""
    bw = max(bx1 - bx0, 1.0)
    bh = max(by1 - by0, 1.0)
    block_area = bw * bh
    for d in drawings:
        ix0 = max(bx0, d["x0"]); iy0 = max(by0, d["y0"])
        ix1 = min(bx1, d["x1"]); iy1 = min(by1, d["y1"])
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        overlap = (ix1 - ix0) * (iy1 - iy0)
        if overlap / block_area >= overlap_threshold:
            return True
    return False


def compute_geometry(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute spatial features for every block of one document.

    Writes du_block_geometry and back-fills du_blocks.doc_y0/doc_y1.
    Idempotent — INSERT OR REPLACE on du_block_geometry, direct UPDATE
    on du_blocks.
    """
    pages    = _fetch_pages(conn, document_id)
    blocks   = _fetch_blocks(conn, document_id)
    images   = _fetch_images(conn, document_id)
    drawings = _fetch_drawings(conn, document_id)
    if not blocks:
        return

    # Cumulative vertical offsets per page (for doc_y coordinates).
    page_offsets: dict[int, float] = {}
    running = 0.0
    for pi in sorted(pages):
        page_offsets[pi] = running
        running += float(pages[pi]["height"] or 0.0)
    document_height = running or None

    # Group blocks by page for per-page median calculations.
    by_page: dict[int, list[dict]] = defaultdict(list)
    for b in blocks:
        by_page[int(b["page_index"])].append(b)

    geom_rows: list[tuple] = []
    doc_coord_rows: list[tuple] = []

    for pi, page_blocks in sorted(by_page.items()):
        meta        = pages.get(pi, {})
        page_width  = float(meta.get("width")  or 0.0)
        page_height = float(meta.get("height") or 0.0)
        doc_offset  = page_offsets.get(pi, 0.0)

        median_left  = _median([b["x0"] for b in page_blocks])
        median_right = _median([b["x1"] for b in page_blocks])

        for i, block in enumerate(page_blocks):
            x0 = float(block["x0"]) if block["x0"] is not None else None
            y0 = float(block["y0"]) if block["y0"] is not None else None
            x1 = float(block["x1"]) if block["x1"] is not None else None
            y1 = float(block["y1"]) if block["y1"] is not None else None

            width    = (x1 - x0) if x0 is not None and x1 is not None else None
            height   = (y1 - y0) if y0 is not None and y1 is not None else None
            center_x = (x0 + x1) / 2.0 if x0 is not None and x1 is not None else None
            center_y = (y0 + y1) / 2.0 if y0 is not None and y1 is not None else None

            prev = page_blocks[i - 1] if i > 0 else None
            nxt  = page_blocks[i + 1] if i + 1 < len(page_blocks) else None

            whitespace_before = (
                y0 - float(prev["y1"])
                if prev is not None and prev["y1"] is not None and y0 is not None
                else None
            )
            whitespace_after = (
                float(nxt["y0"]) - y1
                if nxt is not None and nxt["y0"] is not None and y1 is not None
                else None
            )

            indent_left  = (x0 - median_left)  if x0 is not None and median_left  is not None else None
            indent_right = (median_right - x1)  if x1 is not None and median_right is not None else None

            centeredness = (
                abs(center_x - page_width / 2.0) / (page_width / 2.0)
                if center_x is not None and page_width > 0
                else None
            )

            near_page_top    = _safe_ratio(y0, page_height)
            near_page_bottom = _safe_ratio(
                (page_height - y1) if y1 is not None else None, page_height
            )

            doc_y0 = doc_offset + y0 if y0 is not None else None
            doc_y1 = doc_offset + y1 if y1 is not None else None

            page_y_ratio = _safe_ratio(center_y, page_height)
            doc_center   = (doc_y0 + doc_y1) / 2.0 if doc_y0 is not None and doc_y1 is not None else None
            doc_y_ratio  = _safe_ratio(doc_center, document_height)

            width_ratio  = _safe_ratio(width, page_width)
            height_ratio = _safe_ratio(height, page_height)
            left_margin  = _safe_ratio(x0, page_width)
            right_margin = _safe_ratio(
                (page_width - x1) if x1 is not None else None, page_width
            )

            full_width_like   = int(width_ratio is not None and width_ratio >= 0.72)
            narrow_width_like = int(width_ratio is not None and width_ratio <= 0.38)

            # near_image_score: 1.0 = adjacent to image, 0.0 = far away (≥80pt)
            page_images = images.get(pi, [])
            if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
                dist = _min_distance_to_images(x0, y0, x1, y1, page_images)
                near_image_score = max(0.0, 1.0 - dist / 80.0)
            else:
                near_image_score = 0.0

            # in_colored_box: block is inside a colored background fill.
            # Sidebars, callout boxes, and highlighted sections use this.
            page_drawings = drawings.get(pi, [])
            if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
                in_colored_box = 1 if _block_in_drawing(x0, y0, x1, y1, page_drawings) else 0
            else:
                in_colored_box = 0

            geom_rows.append((
                block["block_id"],
                width, height, center_x, center_y,
                whitespace_before, whitespace_after,
                indent_left, indent_right,
                centeredness,
                near_page_top, near_page_bottom,
                width_ratio, height_ratio,
                page_y_ratio, doc_y_ratio,
                left_margin, right_margin,
                full_width_like, narrow_width_like,
                near_image_score,
                in_colored_box,
            ))

            doc_coord_rows.append((doc_y0, doc_y1, block["block_id"]))

    conn.executemany(
        """
        INSERT INTO du_block_geometry (
            block_id,
            width, height, center_x, center_y,
            whitespace_before, whitespace_after,
            indent_left, indent_right,
            centeredness,
            near_page_top, near_page_bottom,
            width_ratio, height_ratio,
            page_y_ratio, doc_y_ratio,
            left_margin, right_margin,
            full_width_like, narrow_width_like,
            near_image_score, in_colored_box
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            width             = excluded.width,
            height            = excluded.height,
            center_x          = excluded.center_x,
            center_y          = excluded.center_y,
            whitespace_before = excluded.whitespace_before,
            whitespace_after  = excluded.whitespace_after,
            indent_left       = excluded.indent_left,
            indent_right      = excluded.indent_right,
            centeredness      = excluded.centeredness,
            near_page_top     = excluded.near_page_top,
            near_page_bottom  = excluded.near_page_bottom,
            width_ratio       = excluded.width_ratio,
            height_ratio      = excluded.height_ratio,
            page_y_ratio      = excluded.page_y_ratio,
            doc_y_ratio       = excluded.doc_y_ratio,
            left_margin       = excluded.left_margin,
            right_margin      = excluded.right_margin,
            full_width_like   = excluded.full_width_like,
            narrow_width_like = excluded.narrow_width_like,
            near_image_score  = excluded.near_image_score,
            in_colored_box    = excluded.in_colored_box
        """,
        geom_rows,
    )

    # Back-fill doc coordinates into du_blocks (only permitted cross-write
    # from a Layer 1 module — these are geometric coordinates, not signals).
    conn.executemany(
        "UPDATE du_blocks SET doc_y0 = ?, doc_y1 = ? WHERE block_id = ?",
        doc_coord_rows,
    )

    conn.commit()
