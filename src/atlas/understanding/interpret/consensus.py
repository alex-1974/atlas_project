# src/atlas/understanding/interpret/consensus.py
"""Layer 3 — harmonise conflicting role assignments across blocks.

Applies three rules in two iterations:
  1. title_prefix_rule   — suppress multi-block title runs
  2. local_context_rules — caption / reference text corrections
  3. reference_tail_rule — strengthen references after the 50% mark

Bug 3 fix: Role.CONSENSUS_PROTECTED roles (author, page_furniture,
front_matter) are extracted before processing and restored unchanged
afterwards. In the old system these roles were absent from ROLE_ORDER,
causing them to be silently re-scored as 'body'.
"""
from __future__ import annotations

import sqlite3

from atlas.understanding.core.vocab import Role
from atlas.understanding.core.section_labels import (
    REFERENCE_HEADINGS, ALL_BACK_MATTER_HEADINGS,
)


# ── Safe helpers ──────────────────────────────────────────────────────────────

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


# ── Score dict helpers ────────────────────────────────────────────────────────

_SCORE_KEYS = ("title_score", "heading_score", "body_score",
               "reference_score", "caption_score", "noise_score")

_ROLE_TO_SCORE = {
    Role.TITLE:     "title_score",
    Role.HEADING:   "heading_score",
    Role.BODY:      "body_score",
    Role.REFERENCE: "reference_score",
    Role.CAPTION:   "caption_score",
    Role.NOISE:     "noise_score",
}

_RESOLUTION_ORDER = (
    Role.TITLE, Role.HEADING, Role.BODY,
    Role.REFERENCE, Role.CAPTION, Role.NOISE,
)


def _scores(row: dict) -> dict[str, float]:
    return {k: _f(row.get(k)) for k in _SCORE_KEYS}


def _scores_equal(a: dict[str, float], b: dict[str, float]) -> bool:
    return all(abs(a.get(k, 0.0) - b.get(k, 0.0)) < 1e-6 for k in _SCORE_KEYS)


def _set_scores(row: dict, s: dict[str, float]) -> None:
    for k in _SCORE_KEYS:
        row[k] = max(0.0, s[k])


def _best_role(s: dict[str, float]) -> str:
    """Return the role with the highest score above the minimum threshold.

    Falls back to body if no score reaches the threshold — prevents
    zero-score blocks from arbitrarily becoming the first role in the
    resolution order.
    """
    _MIN_SCORE = 0.10
    best, best_val = Role.BODY, _MIN_SCORE - 1e-9  # body wins ties at threshold
    for role in _RESOLUTION_ORDER:
        key = _ROLE_TO_SCORE.get(role)
        if key and s.get(key, 0.0) >= _MIN_SCORE and s[key] > best_val:
            best, best_val = role, s[key]
    return best


# ── Text classifiers ──────────────────────────────────────────────────────────

def _is_reference_heading(text: str) -> bool:
    return _norm(text).lower() in REFERENCE_HEADINGS


def _reference_ish(text: str) -> bool:
    low = _norm(text).lower()
    return any(m in low for m in (
        "doi", "vol.", "volume", "issue", "pp.", "isbn", "issn",
        "publisher", "editors",
    ))


def _caption_ish(text: str) -> bool:
    low = _norm(text).lower()
    return any(low.startswith(p) for p in (
        "fig ", "fig. ", "figure ", "table ", "tab. ",
        "abb. ", "abbildung ", "tabelle ",
    ))


# ── Three consensus rules ─────────────────────────────────────────────────────

def _title_prefix_rule(blocks: list[dict], role_map: dict) -> None:
    """Suppress all but the first consecutive title block at the document start."""
    prefix = 0
    for b in blocks:
        if role_map.get(b["block_id"], {}).get("role") == Role.TITLE:
            prefix += 1
        else:
            break
    if prefix <= 1:
        return
    for b in blocks[1:prefix]:
        row = role_map.get(b["block_id"])
        if not row:
            continue
        s = _scores(row)
        s["title_score"]   *= 0.65
        s["heading_score"] *= 0.90
        s["body_score"]    += 0.05
        _set_scores(row, s)
        row["role"] = _best_role(s)


def _local_context_rules(blocks: list[dict], role_map: dict) -> None:
    total = len(blocks)
    for idx, b in enumerate(blocks):
        row = role_map.get(b["block_id"])
        if not row:
            continue
        text = _norm(b.get("text") or "")
        s    = _scores(row)

        orig_s = {k: s[k] for k in s}
        if s["noise_score"] >= 0.80:
            for k in ("title_score", "heading_score", "body_score"):
                s[k] *= 0.20
            s["reference_score"] *= 0.30
            s["caption_score"]   *= 0.30

        if _caption_ish(text):
            s["caption_score"] += 0.25
            s["body_score"]    *= 0.85

        if _is_reference_heading(text):
            s["reference_score"] += 0.35
            s["heading_score"]   += 0.10

        if _reference_ish(text):
            if idx < int(total * 0.50):
                s["reference_score"] *= 0.55
            else:
                s["reference_score"] += 0.10

        if not _scores_equal(orig_s, s):
            _set_scores(row, s)
            row["role"] = _best_role(s)


def _reference_tail_rule(blocks: list[dict], role_map: dict) -> None:
    """Strengthen reference scores for all blocks after the first reference block
    past the 50% mark."""
    threshold = int(len(blocks) * 0.50)
    first_ref = None

    for idx, b in enumerate(blocks):
        row  = role_map.get(b["block_id"])
        text = _norm(b.get("text") or "")
        if row and (row.get("role") == Role.REFERENCE or _is_reference_heading(text)):
            first_ref = idx
            break

    if first_ref is None or first_ref < threshold:
        return

    for b in blocks[first_ref:]:
        row = role_map.get(b["block_id"])
        if not row:
            continue
        text = _norm(b.get("text") or "")
        s    = _scores(row)
        orig_s = {k: s[k] for k in s}
        if _is_reference_heading(text):
            s["reference_score"] += 0.40
        elif _reference_ish(text):
            s["reference_score"] += 0.20
        if not _scores_equal(orig_s, s):
            _set_scores(row, s)
            row["role"] = _best_role(s)


# ── Database helpers ──────────────────────────────────────────────────────────

def _fetch(conn: sqlite3.Connection, document_id: str) -> tuple[list[dict], list[dict]]:
    blocks = [dict(r) for r in conn.execute(
        "SELECT block_id, text FROM du_blocks WHERE document_id = ? ORDER BY page_index, block_index",
        (document_id,),
    ).fetchall()]
    roles = [dict(r) for r in conn.execute(
        """SELECT block_id, role,
                  title_score, heading_score, body_score,
                  reference_score, caption_score, noise_score
           FROM du_block_roles
           WHERE block_id IN (SELECT block_id FROM du_blocks WHERE document_id = ?)""",
        (document_id,),
    ).fetchall()]
    return blocks, roles


# ── Public API ────────────────────────────────────────────────────────────────

def compute_consensus(conn: sqlite3.Connection, document_id: str) -> None:
    """Harmonise role assignments across blocks.

    Writes updated rows back to du_block_roles. Idempotent.

    Bug 3 fix: roles in Role.CONSENSUS_PROTECTED are extracted before
    the three rules run and restored unchanged afterwards — they are
    never fed into _best_role() which only knows the six scorable roles.
    """
    blocks, role_rows = _fetch(conn, document_id)
    if not blocks or not role_rows:
        return

    # Bug 3 fix: protect author / page_furniture / front_matter
    protected: dict[str, dict] = {}
    active_roles: dict[str, dict] = {}

    for row in role_rows:
        bid = str(row["block_id"])
        if row.get("role") in Role.CONSENSUS_PROTECTED:
            protected[bid] = dict(row)
        else:
            active_roles[bid] = dict(row)

    # Only run rules on the unprotected subset
    active_blocks = [b for b in blocks if str(b["block_id"]) not in protected]

    # Snapshot original scores before any rule modifies them
    original_scores: dict[str, dict[str, float]] = {
        str(row["block_id"]): _scores(row) for row in role_rows
        if str(row["block_id"]) not in protected
    }

    _title_prefix_rule(active_blocks, active_roles)
    for _ in range(2):
        _local_context_rules(active_blocks, active_roles)
        _reference_tail_rule(active_blocks, active_roles)

    # Merge: protected rows written back unchanged.
    # Unprotected rows: keep original role if scores were not modified,
    # otherwise re-derive role from new scores via _best_role.
    final_rows: list[tuple] = []

    for b in blocks:
        bid = str(b["block_id"])
        row = protected.get(bid) or active_roles.get(bid)
        if not row:
            continue
        s = _scores(row)
        if bid in protected:
            role = row["role"]
        elif _scores_equal(s, original_scores.get(bid, {})):
            role = row["role"]   # scores unchanged — trust _resolve_role
        else:
            role = _best_role(s)  # scores modified by consensus rules
        final_rows.append((
            bid, role,
            s["title_score"], s["heading_score"], s["body_score"],
            s["reference_score"], s["caption_score"], s["noise_score"],
        ))

    conn.executemany(
        """
        INSERT INTO du_block_roles (
            block_id, role,
            title_score, heading_score, body_score,
            reference_score, caption_score, noise_score
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            role            = excluded.role,
            title_score     = excluded.title_score,
            heading_score   = excluded.heading_score,
            body_score      = excluded.body_score,
            reference_score = excluded.reference_score,
            caption_score   = excluded.caption_score,
            noise_score     = excluded.noise_score
        """,
        final_rows,
    )
    conn.commit()
