# src/atlas/understanding/measure/surface.py
"""Layer 1 — surface text features per block.

Pure text analysis, no geometric knowledge. Reads du_blocks,
writes du_block_surface. No imports from other DU modules.
"""
from __future__ import annotations

import re
import sqlite3


_URL_RE   = re.compile(r"https?://|www\.", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
_DOI_RE   = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
_YEAR_RE  = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
_SENT_RE  = re.compile(r"[.!?]+")

# Letter-spacing pattern (Fall B): single characters separated by spaces.
# Matches: "T H E P A T T E R N", "B U R G A G E  P L O T S"
# Requires at least 4 spaced tokens to avoid false positives on initials.
# Each token is 1–3 chars (single letter or short cluster like "AT", "RG").
_LETTER_SPACED_RE = re.compile(
    r'^(?:[A-Za-z\u00C0-\u00FF]{1,3}\s+){3,}[A-Za-z\u00C0-\u00FF]{1,3}\s*$'
)


def _sentence_count(text: str) -> int:
    return len([p for p in _SENT_RE.split(text) if p.strip()]) if text else 0


def _density(text: str, predicate) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if predicate(ch)) / max(1, len(text))


def compute_surface(conn: sqlite3.Connection, document_id: str) -> None:
    """Compute surface text features for every block of one document.

    Writes du_block_surface. Idempotent via INSERT OR REPLACE.
    """
    blocks = conn.execute(
        "SELECT block_id, text FROM du_blocks WHERE document_id = ? ORDER BY block_index",
        (document_id,),
    ).fetchall()
    if not blocks:
        return

    rows: list[tuple] = []
    for block in blocks:
        text  = block["text"] or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        flat  = " ".join(lines)
        words = flat.split()

        rows.append((
            block["block_id"],
            len(flat),
            len(words),
            _sentence_count(flat),
            len(lines),
            (sum(len(ln) for ln in lines) / len(lines)) if lines else 0.0,
            None,                                          # line_width_ratio: needs geometry
            _density(flat, str.isupper),                   # capitalization_ratio
            _density(flat, lambda c: c in ".,;:!?()[]{}'\"-"),  # punctuation_density
            _density(flat, str.isdigit),                   # digit_density
            int(bool(flat) and flat.isupper()),             # is_all_caps
            int(len(words) <= 6),                          # is_short_line
            int(flat.rstrip().endswith(".")),              # ends_with_period
            int(flat.rstrip().endswith(":")),              # ends_with_colon
            int(flat[:1].isdigit()),                       # starts_with_number
            int(flat[:1] in {"-", "*", "•"}),             # starts_with_bullet
            int("(" in flat or ")" in flat),               # contains_parentheses
            int("[" in flat or "]" in flat),               # contains_brackets
            int(bool(_URL_RE.search(flat))),               # contains_url
            int(bool(_EMAIL_RE.search(flat))),             # contains_email
            int(bool(_DOI_RE.search(flat))),               # contains_doi
            int(bool(_YEAR_RE.search(flat))),              # contains_year
        ))

    conn.executemany(
        """
        INSERT INTO du_block_surface (
            block_id,
            char_count, word_count, sentence_count, line_count,
            mean_line_length, line_width_ratio,
            capitalization_ratio, punctuation_density, digit_density,
            is_all_caps, is_short_line,
            ends_with_period, ends_with_colon,
            starts_with_number, starts_with_bullet,
            contains_parentheses, contains_brackets,
            contains_url, contains_email, contains_doi, contains_year
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            char_count           = excluded.char_count,
            word_count           = excluded.word_count,
            sentence_count       = excluded.sentence_count,
            line_count           = excluded.line_count,
            mean_line_length     = excluded.mean_line_length,
            line_width_ratio     = excluded.line_width_ratio,
            capitalization_ratio = excluded.capitalization_ratio,
            punctuation_density  = excluded.punctuation_density,
            digit_density        = excluded.digit_density,
            is_all_caps          = excluded.is_all_caps,
            is_short_line        = excluded.is_short_line,
            ends_with_period     = excluded.ends_with_period,
            ends_with_colon      = excluded.ends_with_colon,
            starts_with_number   = excluded.starts_with_number,
            starts_with_bullet   = excluded.starts_with_bullet,
            contains_parentheses = excluded.contains_parentheses,
            contains_brackets    = excluded.contains_brackets,
            contains_url         = excluded.contains_url,
            contains_email       = excluded.contains_email,
            contains_doi         = excluded.contains_doi,
            contains_year        = excluded.contains_year
        """,
        rows,
    )
    conn.commit()
