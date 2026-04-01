# src/atlas/understanding/interpret/roles.py
"""Layer 3 — assign discrete semantic roles to blocks.

Reads du_block_signals and du_block_furniture, applies text heuristics
and early-meta context adjustments, writes du_block_roles.

Bug 2 fix: early_meta key is 'strong_journal_header', not 'has_journal_meta'.
All role constants come from vocab.Role — no local string literals.
"""
from __future__ import annotations

import sqlite3

from atlas.understanding.core.vocab import Role
from atlas.understanding.interpret.early_meta import detect_early_meta_signals
from atlas.understanding.core.section_labels import (
    REFERENCE_HEADINGS, ABSTRACT_HEADINGS, APPENDIX_HEADINGS,
)
from atlas.understanding.core.text_patterns import is_formula_label
from atlas.understanding.interpret.document_type import apply_type_adjustments, BlockScores
from atlas.core.fuzzy import (
    for_ as _for, fnot as _fnot,
    fscale as _fscale, fboost as _fboost,
    fdampen as _fdampen, flinear as _flinear,
)


# ── Safe helpers ──────────────────────────────────────────────────────────────

def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def _wc(text: str) -> int:
    return len(text.split()) if text else 0


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


# ── Text classifiers (local — heavier than text_patterns, role-aware) ────────

def _sentence_like(text: str) -> bool:
    if _wc(text) < 6:
        return False
    return text.endswith((".", ";", ":"))


import re as _re
_AUTHOR_INITIALS = _re.compile(r'\b[A-Z]\.')
_AUTHOR_CONJ    = _re.compile(r'\b([A-Z][a-zA-Z]+|[A-Z]\.) (and|und) ([A-Z][a-zA-Z]+|[A-Z]\.)\b')
_AUTHOR_PREFIX  = _re.compile(r'\b(von|van|de|del|della|di)\b', _re.IGNORECASE)
_AUTHOR_SUFFIX  = _re.compile(r'\b(Dr\.|Prof\.|PhD|IgB|M\.A\.|B\.A\.|Dipl\.|Mag\.|M\.Sc\.)\b')


def _author_line_like(text: str) -> bool:
    wc = _wc(text)
    if wc < 2 or wc > 12:
        return False
    low = text.lower()
    bad = ("university", "universität", "faculty", "department", "institute",
           "journal", "vol.", "abstract", "submitted", "accepted",
           "doi", "@", "copyright")
    if any(m in low for m in bad):
        return False
    # Explicit "By Author" pattern
    stripped = text.strip()
    if stripped.lower().startswith("by "):
        rest = stripped[3:].strip()
        if _wc(rest) >= 2:
            return True
    # Requires at least one name-specific signal — prevents topic headings
    # like "Das Niederdeutsche Hallenhaus" from matching
    has_name = bool(
        _AUTHOR_INITIALS.search(text)
        or _AUTHOR_SUFFIX.search(text)
        or _AUTHOR_PREFIX.search(text)
        or _AUTHOR_CONJ.search(text)
        or ("," in text and wc <= 8)
    )
    if not has_name:
        return False
    alpha = [w.strip(",;:.()[]") for w in text.split() if any(c.isalpha() for c in w)]
    if len(alpha) < 2:
        return False
    upper = sum(1 for w in alpha if w and w[0].isupper())
    return upper >= max(2, len(alpha) - 1)


def _journal_header_like(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in (
        "journal", "review", "vol.", "volume", "issue", "no.", "issn",
        "copyright", "published by",
    ))


def _strong_title_line(text: str) -> bool:
    wc = _wc(text)
    if wc < 2 or wc > 18:
        return False
    if _sentence_like(text) or text.endswith("."):
        return False
    caps = _caps_ratio(text)
    # All-caps titles
    if text.isupper() and wc <= 12:
        return True
    # Title-case or mixed caps
    if text.istitle() or (0.15 <= caps <= 0.95 and wc <= 12):
        return True
    # Sentence-case title: starts with capital letter (possibly after opening quote).
    # Covers "„In großen Hütten, die man Häuser nennt…"" and similar.
    stripped = text.lstrip('„\'"«‹')
    if stripped and stripped[0].isupper() and wc <= 14:
        return True
    return False


def _heading_text_like(text: str, font_size: float = 0.0,
                        is_letter_spaced: bool = False) -> bool:
    wc = _wc(text)
    # Letter-spaced text has inflated word count due to spaces between chars.
    # Use a collapsed version for the word-count check.
    if is_letter_spaced:
        from atlas.understanding.core.text_patterns import normalize_letter_spaced
        collapsed = normalize_letter_spaced(text)
        wc = _wc(collapsed)
    if wc == 0 or wc > 18:
        return False
    if _sentence_like(text) or text.endswith("."):
        return False
    # Single word at small font = map label / legend, not a heading.
    # Exception: letter-spaced text at small font IS a heading device.
    if wc == 1 and font_size > 0 and font_size < 9.0 and not is_letter_spaced:
        return False
    low = text.lower()
    if low in ABSTRACT_HEADINGS | REFERENCE_HEADINGS | APPENDIX_HEADINGS | {"contents"}:
        return True
    if text.istitle() and wc <= 8:
        return True
    if _caps_ratio(text) > 0.55 and wc <= 10:
        return True
    if wc <= 4:
        return True
    # Longer headings: starts with capital + no sentence structure
    # e.g. "Das Niederdeutsche Hallenhaus ist Bauernhaus des Jahres 2023"
    if (text[0].isupper()
            and not text.endswith((".", "?", "!"))
            and wc <= 14):
        return True
    return False


def _caption_like(text: str) -> bool:
    low = text.lower()
    return any(low.startswith(p) for p in (
        "figure ", "fig. ", "fig ", "table ", "tab. ",
        "abb. ", "abbildung ", "tabelle ",
    ))


def _reference_ish(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in (
        "vol.", "volume", "issue", "pp.", "doi",
        "editor", "journal", "publisher", "isbn", "issn",
    ))


# ── Role resolution ───────────────────────────────────────────────────────────

def _resolve_role(
    text: str,
    title_score: float,
    heading_score: float,
    body_score: float,
    author_score: float,
    reference_score: float,
    caption_score: float,
    noise_score: float,
    furniture: dict,
    font_size: float = 0.0,
    is_letter_spaced: bool = False,
) -> str:
    wc = _wc(text)

    # 1. Page furniture
    if (furniture.get("running_header_like")
            or furniture.get("running_footer_like")
            or furniture.get("page_number_like")):
        return Role.PAGE_FURNITURE

    # 2. Noise
    if not text:
        return Role.NOISE
    if noise_score >= max(body_score, heading_score, title_score, 0.85):
        return Role.NOISE

    # 3. Caption
    if (caption_score >= max(reference_score, heading_score, body_score,
                              title_score, noise_score)
            and caption_score >= 0.15):
        return Role.CAPTION

    # 4. Author — before reference, because author lines often contain years,
    #    initials, and punctuation that also scores as reference.
    #    Two tiers: high-confidence fires unconditionally;
    #    medium-confidence fires only when reference/caption don't dominate.
    if _author_line_like(text):
        if author_score >= max(heading_score + 0.15, body_score, 0.50):
            return Role.AUTHOR
        if (author_score >= 0.25
                and author_score >= reference_score
                and author_score >= caption_score):
            return Role.AUTHOR

    # 5. Reference
    if (reference_score >= max(heading_score, body_score, title_score, noise_score)
            and reference_score >= 0.15):
        return Role.REFERENCE

    # 6. Author / title (first-page context)
    if furniture.get("first_page_meta_like"):
        if _author_line_like(text):
            return Role.AUTHOR
        if (title_score >= max(heading_score + 0.10, body_score + 0.25, 0.75)
                and _strong_title_line(text) and wc <= 14):
            return Role.TITLE
        if _journal_header_like(text):
            return Role.FRONT_MATTER

    # 7. Title (without first-page context, high confidence)
    #    Also fires when largest_on_page even if heading_score is higher —
    #    a block that is literally the largest on its page and reads like a
    #    title should not be downgraded to heading just because heading_score
    #    edges it out.
    if (_strong_title_line(text) and wc <= 14
            and title_score >= max(body_score + 0.35, 0.55)):
        if title_score >= heading_score - 0.30:   # title within 0.30 of heading
            return Role.TITLE

    # 8. Heading
    if _heading_text_like(text, font_size=font_size,
                           is_letter_spaced=is_letter_spaced):
        if (heading_score >= max(body_score + 0.05, title_score - 0.10, noise_score)
                and heading_score >= 0.15):
            return Role.HEADING
        if (heading_score >= 0.40
                and body_score < 0.85
                and heading_score >= title_score - 0.10
                and heading_score >= noise_score):
            return Role.HEADING

    # 9. Body (fallback)
    return Role.BODY


# ── Database helpers ──────────────────────────────────────────────────────────

def _fetch_blocks(conn: sqlite3.Connection, document_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """
        SELECT b.block_id, b.text, b.page_index,
               s.title_like, s.heading_like, s.body_like, s.author_like,
               s.reference_like, s.caption_like, s.noise_like,
               f.running_header_like, f.running_footer_like,
               f.page_number_like, f.first_page_meta_like,
               t.bold, t.font_ratio, t.font_size,
               COALESCE(t.is_letter_spaced, 0) AS is_letter_spaced,
               sp.paragraph_gap_before,
               COALESCE(g.doc_y_ratio, 0.0) AS doc_y_ratio
        FROM du_blocks b
        LEFT JOIN du_block_signals   s  ON s.block_id  = b.block_id
        LEFT JOIN du_block_furniture f  ON f.block_id  = b.block_id
        LEFT JOIN du_block_typography t  ON t.block_id  = b.block_id
        LEFT JOIN du_block_spacing   sp ON sp.block_id = b.block_id
        LEFT JOIN du_block_geometry  g  ON g.block_id  = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.page_index, b.block_index
        """,
        (document_id,),
    ).fetchall()]


# ── Public API ────────────────────────────────────────────────────────────────

def compute_roles(conn: sqlite3.Connection, document_id: str) -> None:
    """Assign a discrete role to every block of one document.

    Writes du_block_roles. Idempotent via INSERT OR REPLACE.
    """
    blocks = _fetch_blocks(conn, document_id)
    if not blocks:
        return

    # Bug 2 fix: key is 'strong_journal_header', not 'has_journal_meta'
    early_meta = detect_early_meta_signals(blocks)

    # Load document type probability vector for weighted signal adjustments.
    # May be None on first pass (before compute_document_type runs).
    type_row = conn.execute(
        "SELECT du_document_type_scores FROM documents WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    type_scores_json = type_row[0] if type_row else None

    rows: list[tuple] = []

    for block in blocks:
        text = _norm(block.get("text"))
        low  = text.lower()

        title_s   = _f(block.get("title_like"))
        heading_s = _f(block.get("heading_like"))
        body_s    = _f(block.get("body_like"))
        ref_s     = _f(block.get("reference_like"))
        cap_s     = _f(block.get("caption_like"))
        noise_s   = _f(block.get("noise_like"))

        furniture = {
            "running_header_like":  bool(block.get("running_header_like")),
            "running_footer_like":  bool(block.get("running_footer_like")),
            "page_number_like":     bool(block.get("page_number_like")),
            "first_page_meta_like": bool(block.get("first_page_meta_like")),
        }

        # ── Score adjustments via fuzzy operators ─────────────────────────
        fs  = _f(block.get("font_size"))
        letter_spaced = bool(block.get("is_letter_spaced"))
        # For letter-spaced blocks, use collapsed word count to avoid
        # inflated wc from spaces between individual characters.
        if letter_spaced:
            from atlas.understanding.core.text_patterns import normalize_letter_spaced
            wc = _wc(normalize_letter_spaced(block.get("text") or ""))
        else:
            wc = _wc(text)
        char_count = len(text)
        sent_like  = _sentence_like(text)

        if furniture["first_page_meta_like"]:
            title_s   = _fboost(title_s,   0.15)
            heading_s = _fboost(heading_s, 0.08)
            body_s    = _fdampen(body_s,   0.15)

        if any((furniture["running_header_like"],
                furniture["running_footer_like"],
                furniture["page_number_like"])):
            noise_s   = max(noise_s, 0.90)
            title_s   = _fscale(title_s,   0.10)
            heading_s = _fscale(heading_s, 0.10)
            body_s    = _fscale(body_s,    0.10)
            ref_s     = _fscale(ref_s,     0.10)
            cap_s     = _fscale(cap_s,     0.10)

        if early_meta.get("strong_journal_header") and _journal_header_like(text):
            if furniture["first_page_meta_like"]:
                title_s = _fboost(title_s, 0.05)
            else:
                ref_s   = _fboost(ref_s,   0.07)

        if type_scores_json:
            block_ctx = {
                "in_column_context": _f(block.get("paragraph_gap_before")) < 0,
                "bold_or_large":     bool(block.get("bold")) or _f(block.get("font_ratio")) > 1.10,
            }
            bs = BlockScores(title_s, heading_s, body_s, _f(block.get("author_like")),
                             ref_s, cap_s, noise_s)
            bs = apply_type_adjustments(block_ctx, bs, type_scores_json)
            bs.clamp()
            title_s, heading_s, body_s = bs.title_like, bs.heading_like, bs.body_like
            ref_s, cap_s, noise_s = bs.reference_like, bs.caption_like, bs.noise_like

        # Titles almost always appear in the first ~15% of the document.
        # A block far into the document with high title_like is likely a
        # prominent sub-heading, not the document title.
        doc_y = _f(block.get("doc_y_ratio"))
        if doc_y > 0.15 and not furniture["first_page_meta_like"]:
            title_s = _fscale(title_s, 0.30)

        if _author_line_like(text):
            title_s   = _fscale(title_s,   0.55)
            heading_s = _fscale(heading_s, 0.65)
            body_s    = _fscale(body_s,    0.70)

        if _caption_like(text):
            cap_s     = _fboost(cap_s,     0.35)
            title_s   = _fscale(title_s,   0.25)
            heading_s = _fscale(heading_s, 0.60)

        if _reference_ish(text):
            ref_s   = _fboost(ref_s,   0.15)
            title_s = _fscale(title_s, 0.40)

        if low in REFERENCE_HEADINGS | APPENDIX_HEADINGS:
            heading_s = _fboost(heading_s, 0.25)
            ref_s     = _fboost(ref_s,     0.25)
            title_s   = _fscale(title_s,   0.30)

        # Long text suppresses title/heading
        if wc >= 15:
            title_s   = _fscale(title_s,   0.35)
        if wc >= 30:
            title_s   = _fscale(title_s,   0.10)
            heading_s = _fscale(heading_s, 0.75)
        if char_count >= 120:
            title_s   = _fscale(title_s,   0.30)
        if char_count >= 250:
            title_s   = _fscale(title_s,   0.08)
            heading_s = _fscale(heading_s, 0.70)
        if sent_like:
            title_s   = _fscale(title_s,   0.20)
            heading_s = _fscale(heading_s, 0.75)
            body_s    = _fboost(body_s,    0.20)
        if text.endswith("."):
            title_s   = _fscale(title_s,   0.20)
        if wc >= 20 and not furniture["first_page_meta_like"]:
            body_s    = _fboost(body_s,    0.25)

        # heading bonus — only applies when heading_s already has some signal.
        if _heading_text_like(text, font_size=fs,
                               is_letter_spaced=letter_spaced) and heading_s > 0.20:
            single_word_small = 1.0 if (wc == 1 and fs > 0 and fs < 9.0) else 0.0
            text_boost = _fscale(
                _for(0.12, 0.08 if wc <= 5 else 0.0),
                _fdampen(1.0, single_word_small),
            )
            heading_s = _fboost(heading_s, text_boost)

        if wc >= 25:
            body_s = _fboost(body_s, 0.22)
        if wc >= 40:
            body_s = _fboost(body_s, 0.25)

        # Formula / calculation step labels (e.g. "Given:", "Bending stress:",
        # "Effective length (Table …):") are not section headings.
        # They appear inside worked examples, are short, end with a colon,
        # and start with a known engineering step keyword or structural noun.
        # Dampen heading and title strongly; body remains so the block falls
        # through to the body fallback in _resolve_role.
        if is_formula_label(text):
            heading_s = _fscale(heading_s, 0.10)
            title_s   = _fscale(title_s,   0.10)

        # Letter-spaced text is a typographic heading device — dampen body_s
        # so that the heading classification can win even when char_count is
        # inflated by the spaces between individual characters.
        if block.get("is_letter_spaced"):
            body_s = _fscale(body_s, 0.20)

        title_s   = max(0.0, title_s)
        heading_s = max(0.0, heading_s)
        body_s    = max(0.0, body_s)
        ref_s     = max(0.0, ref_s)
        cap_s     = max(0.0, cap_s)
        noise_s   = max(0.0, noise_s)

        role = _resolve_role(
            text=text,
            title_score=title_s,
            heading_score=heading_s,
            body_score=body_s,
            author_score=_f(block.get("author_like")),
            reference_score=ref_s,
            caption_score=cap_s,
            noise_score=noise_s,
            furniture=furniture,
            font_size=_f(block.get("font_size")),
            is_letter_spaced=letter_spaced,
        )

        rows.append((
            block["block_id"], role,
            title_s, heading_s, body_s, ref_s, cap_s, noise_s,
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
        rows,
    )
    conn.commit()
