# src/atlas/understanding/measure/furniture.py
"""Layer 1 — page furniture detection (headers, footers, page numbers).

Reads du_blocks joined with du_pages and du_block_topology.
Writes du_block_furniture — including repeated_hint.

Bug 3 fix: repeated_hint lives HERE, not in du_block_topology.
This module does NOT write to any other Layer 1 table.

Algorithm (two stages):
  Stage 1 — band position: is the block in the top 12 % or bottom 10 %
            of the page?
  Stage 2 — repetition check: does the same text (after page-number
            normalisation) appear on ≥ 2 pages? Parity-aware for
            two-sided layouts.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter


_HEADER_BAND = 0.12
_FOOTER_BAND = 0.10
_HEADER_WORD_MAX = 16

_PAGE_NUM_RE = re.compile(r"^\d{1,4}$")


# ── Text helpers ──────────────────────────────────────────────────────────────

def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


def _norm_running(text: str | None) -> str:
    """Strip leading/trailing page numbers for repetition matching."""
    t = _norm(text)
    t = re.sub(r"^\d+\s+", "", t)
    t = re.sub(r"\s+\d+$", "", t)
    return t.strip()


def _word_count(text: str | None) -> int:
    return len((text or "").split())


def _caps_ratio(text: str | None) -> float:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


# ── Band / text classifiers ───────────────────────────────────────────────────

def _band(y0: float | None, y1: float | None,
          page_height: float | None) -> str | None:
    if y0 is None or y1 is None or not page_height:
        return None
    if float(y1) <= float(page_height) * _HEADER_BAND:
        return "header"
    if float(y0) >= float(page_height) * (1.0 - _FOOTER_BAND):
        return "footer"
    return None


def _page_number_like(text: str | None) -> bool:
    return bool(_PAGE_NUM_RE.fullmatch(_norm(text or "").strip()))


def _first_page_meta_like(text: str | None) -> bool:
    low = _norm(text)
    return any(tok in low for tok in (
        "doi:", "doi ", "copyright", "©", "vol.", "volume",
        "issue", "openchoice", "creative commons",
    ))


def _running_header_text_like(text: str | None) -> bool:
    value = " ".join((text or "").split()).strip()
    if not value or _page_number_like(value):
        return False
    wc = _word_count(value)
    if wc == 0 or wc > _HEADER_WORD_MAX:
        return False
    return (
        value[:1].isdigit()
        or _caps_ratio(value) >= 0.55
        or value.istitle()
    )


def _running_footer_text_like(text: str | None) -> bool:
    value = " ".join((text or "").split()).strip()
    if not value:
        return False
    low = value.lower()
    if any(tok in low for tok in ("doi", "copyright", "creative commons")):
        return True
    if _page_number_like(value):
        return True
    return _word_count(value) <= 12 and _caps_ratio(value) >= 0.5


# ── Database reads ────────────────────────────────────────────────────────────

def _fetch_blocks(conn: sqlite3.Connection,
                  document_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT b.block_id, b.page_index, b.block_index, b.text,
               b.y0, b.y1,
               p.height AS page_height,
               t.odd_even_page
        FROM du_blocks b
        LEFT JOIN du_pages    p ON p.document_id = b.document_id
                                AND p.page_index  = b.page_index
        LEFT JOIN du_block_topology t ON t.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.page_index, b.block_index
        """,
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Main ──────────────────────────────────────────────────────────────────────

def compute_furniture(conn: sqlite3.Connection, document_id: str) -> None:
    """Detect headers, footers, and page numbers.

    Writes du_block_furniture. Idempotent via INSERT OR REPLACE.
    Does NOT write to du_block_topology (Bug 3 fix).
    """
    blocks = _fetch_blocks(conn, document_id)
    if not blocks:
        return

    # Stage 1: count how often each normalised text appears per band / parity.
    repeated:        Counter = Counter()
    parity_repeated: Counter = Counter()

    for b in blocks:
        text       = b.get("text") or ""
        page_index = int(b["page_index"])
        odd_even   = b.get("odd_even_page")
        bn         = _band(b.get("y0"), b.get("y1"), b.get("page_height"))

        if bn == "header":
            key = ("header", _norm_running(text))
            repeated[key] += 1
            if odd_even:
                parity_repeated[("header", odd_even, _norm_running(text))] += 1
        elif bn == "footer":
            key = ("footer", _norm(text))
            repeated[key] += 1
            if odd_even:
                parity_repeated[("footer", odd_even, _norm(text))] += 1

    # Stage 2: emit one row per block.
    rows: list[tuple] = []

    for b in blocks:
        text       = b.get("text") or ""
        page_index = int(b["page_index"])
        odd_even   = b.get("odd_even_page")
        bn         = _band(b.get("y0"), b.get("y1"), b.get("page_height"))

        is_top    = int(bn == "header")
        is_bottom = int(bn == "footer")
        pg_num    = int(_page_number_like(text))
        fp_meta   = int(page_index == 0 and _first_page_meta_like(text))

        rep_cross  = False
        rep_parity = False
        hdr_like   = False
        ftr_like   = False

        if is_top:
            nrm = _norm_running(text)
            rep_cross  = repeated[("header", nrm)] >= 2
            rep_parity = bool(odd_even and parity_repeated[("header", odd_even, nrm)] >= 2)
            hdr_like   = bool(
                not fp_meta
                and (rep_cross or rep_parity or _running_header_text_like(text))
            )

        if is_bottom:
            nrm = _norm(text)
            rep_cross  = rep_cross  or repeated[("footer", nrm)] >= 2
            rep_parity = rep_parity or bool(
                odd_even and parity_repeated[("footer", odd_even, nrm)] >= 2
            )
            ftr_like = bool(
                not fp_meta
                and (rep_cross or rep_parity or _running_footer_text_like(text))
            )

        repeated_hint = int(
            not fp_meta
            and (hdr_like or ftr_like or (pg_num and bool(is_top or is_bottom)))
        )

        rows.append((
            b["block_id"],
            is_top, is_bottom,
            pg_num,
            int(hdr_like), int(ftr_like),
            int(rep_cross), int(rep_parity),
            fp_meta,
            repeated_hint,          # lives here, NOT in du_block_topology
        ))

    conn.executemany(
        """
        INSERT INTO du_block_furniture (
            block_id,
            is_top_band, is_bottom_band,
            page_number_like,
            running_header_like, running_footer_like,
            repeated_across_pages, repeated_same_parity,
            first_page_meta_like,
            repeated_hint
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            is_top_band           = excluded.is_top_band,
            is_bottom_band        = excluded.is_bottom_band,
            page_number_like      = excluded.page_number_like,
            running_header_like   = excluded.running_header_like,
            running_footer_like   = excluded.running_footer_like,
            repeated_across_pages = excluded.repeated_across_pages,
            repeated_same_parity  = excluded.repeated_same_parity,
            first_page_meta_like  = excluded.first_page_meta_like,
            repeated_hint         = excluded.repeated_hint
        """,
        rows,
    )
    conn.commit()
