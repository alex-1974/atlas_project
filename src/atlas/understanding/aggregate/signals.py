# src/atlas/understanding/aggregate/signals.py
"""Layer 2 — aggregate all Layer 1 measurements into named scores.

Each score is a fuzzy membership value in [0.0, 1.0] computed from
Layer 1 features using operators from core.fuzzy.  The design principle:
every formula should read as a logical statement about the block, not
as an accumulating point counter.

Key design decisions
--------------------
- fand() = strict conjunction: all conditions must hold.
  Use when absence of any one condition should collapse the score.
- for_() = soft disjunction: evidence from multiple sources combines
  without exceeding 1.0.
- fguard(signal, gate) = gated signal: if gate == 0 the signal is 0.
  Used for author_like so that purely positional signals (short_line,
  no_dot) cannot fire without a name-specific gate.

Signals added vs. old system
-----------------------------
- italic now contributes to heading_like, reference_like, caption_like
- larger_than_prev/next used in heading_like
- alignment_center used in title_like
- word_count used alongside char_count in body_like
- author_like gated on name_signal (fixes Ortsname false positives)

Profile-driven weights
----------------------
An optional DocumentProfile (from pipeline/profiling.py) can be passed
to compute_signals().  This prepares the Aggregate layer for
quadrant-specific weight optimisation via Ground Truth validation.

Currently a stub — all quadrants use identical weights.
Activation sequence:
  1. Collect Ground Truth for all four quadrants.
  2. Identify which weights diverge between quadrants.
  3. Replace stub constants with _QUADRANT_WEIGHTS[quadrant].field.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.pipeline.profiling import DocumentProfile

from atlas.core.fuzzy import (
    fand, for_, fnot, fguard, fscale, fboost, fdampen, flinear, fmax,
)


# ── Safe coercions ────────────────────────────────────────────────────────────

def _b(value) -> float:
    return 1.0 if value else 0.0


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ── Name-signal detection (gate for author_like) ──────────────────────────────

_INITIALS_RE  = re.compile(r'\b[A-Z]\.\s')
_NAME_CONJ_RE = re.compile(r'\b([A-Z][a-z]+|[A-Z]\.) (and|und) ([A-Z][a-z]+|[A-Z]\.)\b')
_NAME_PREFIX  = re.compile(r'\b(von|van|de|del|della|di)\b', re.IGNORECASE)
_NAME_SUFFIX  = re.compile(r'\b(Dr\.|Prof\.|PhD|IgB|M\.A\.|B\.A\.|Dipl\.|Mag\.)\b')


def _name_signal(text: str | None) -> float:
    """Fuzzy membership: does this text look like a personal name?

    Returns a value in [0, 1] used as a gate for author_like.
    Without a name-specific indicator the author score collapses to 0.
    """
    t = (text or "").strip()
    if not t:
        return 0.0
    if _INITIALS_RE.search(t):
        return 1.0
    if _NAME_SUFFIX.search(t):
        return 1.0
    if "," in t:
        return 0.9
    if _NAME_CONJ_RE.search(t):
        return 0.6
    if _NAME_PREFIX.search(t):
        return 0.7
    return 0.0


# ── Main ──────────────────────────────────────────────────────────────────────

def compute_signals(
    conn: sqlite3.Connection,
    document_id: str,
    profile: "DocumentProfile | None" = None,
) -> None:
    """Aggregate Layer 1 measurements into seven named scores per block.

    Parameters
    ----------
    conn : sqlite3.Connection
    document_id : str
    profile : DocumentProfile | None
        Pre-classification result from Pass 0 (pipeline/profiling.py).
        Currently a stub — quadrant is read but weights are not yet
        differentiated.  Ground Truth validation will determine which
        weights to vary per quadrant.
    """
    # ── Quadrant stub ─────────────────────────────────────────────────────────
    # quadrant = profile.quadrant if profile is not None else "doc_structured"
    #
    # Quadrant-specific weights will be activated here after Ground Truth
    # validation identifies which signals diverge between quadrants.
    # For now all quadrants use identical weights — fully backwards compatible.
    # ─────────────────────────────────────────────────────────────────────────

    rows = conn.execute(
        """
        SELECT
            b.block_id,
            b.text,

            g.centeredness,
            g.full_width_like,
            g.narrow_width_like,
            COALESCE(g.near_image_score, 0.0) AS near_image_score,
            COALESCE(g.in_colored_box, 0)     AS in_colored_box,

            t.bold,
            t.italic,
            COALESCE(t.is_letter_spaced, 0)   AS is_letter_spaced,
            t.all_caps          AS typo_all_caps,
            t.small_caps,
            t.largest_on_page,
            t.font_ratio,
            t.font_percentile,
            COALESCE(t.text_color, 0)   AS text_color,
            COALESCE(t.color_rank,  0)  AS color_rank,
            COALESCE(t.is_serif,    0)  AS is_serif,
            t.larger_than_prev,
            t.larger_than_next,
            t.font_size_delta_prev,

            topo.page_transition_before  AS is_first_on_page,
            topo.page_transition_after   AS is_last_on_page,

            f.repeated_hint,
            f.first_page_meta_like,

            sm.is_references_marker,
            sm.is_figure_marker,
            sm.is_table_marker,
            sm.contains_doi,
            sm.contains_year,
            sm.contains_citation_bracket,
            sm.contains_citation_author_year,
            COALESCE(sm.contains_chapter_number, 0) AS contains_chapter_number,

            sf.char_count,
            sf.word_count,
            sf.sentence_count,
            sf.punctuation_density,
            sf.digit_density,
            sf.ends_with_period,
            sf.ends_with_colon,
            sf.contains_parentheses,
            sf.is_short_line,
            sf.starts_with_number,

            sp.continuation_like,
            sp.paragraph_gap_before,
            sp.alignment_center,
            COALESCE(sp.in_flow_score, 0.5) AS in_flow_score,

            ctx.front_matter_score,
            ctx.body_score,
            ctx.back_matter_score

        FROM du_blocks b
        LEFT JOIN du_block_geometry      g    ON g.block_id   = b.block_id
        LEFT JOIN du_block_typography    t    ON t.block_id   = b.block_id
        LEFT JOIN du_block_topology      topo ON topo.block_id = b.block_id
        LEFT JOIN du_block_furniture     f    ON f.block_id   = b.block_id
        LEFT JOIN du_block_semantic_micro sm  ON sm.block_id  = b.block_id
        LEFT JOIN du_block_surface       sf   ON sf.block_id  = b.block_id
        LEFT JOIN du_block_spacing       sp   ON sp.block_id  = b.block_id
        LEFT JOIN du_block_context       ctx  ON ctx.block_id = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.page_index, b.block_index
        """,
        (document_id,),
    ).fetchall()

    if not rows:
        return

    signal_rows: list[tuple] = []

    for r in rows:
        text = r["text"] or ""

        # ── Raw features ──────────────────────────────────────────────────
        bold        = _b(r["bold"])
        italic      = _b(r["italic"])
        letter_spaced = _b(r["is_letter_spaced"])
        all_caps    = _b(r["typo_all_caps"]) or (1.0 if text.isupper() and len(text) > 4 else 0.0)
        largest     = _b(r["largest_on_page"])
        font_ratio  = _f(r["font_ratio"])
        font_pct    = _f(r["font_percentile"])   # 0=smallest, 1=largest in doc
        color_rank  = int(r["color_rank"] or 0)  # 0=body color, 1=heading color, 2+=rare
        larger_prev = _b(r["larger_than_prev"])
        larger_next = _b(r["larger_than_next"])
        delta_prev  = _f(r["font_size_delta_prev"])

        full_wide      = _b(r["full_width_like"])
        narrow         = _b(r["narrow_width_like"])
        near_image     = _f(r["near_image_score"])
        in_colored_box = _b(r["in_colored_box"])
        centered    = _f(r["centeredness"])
        align_ctr   = _f(r["alignment_center"])

        repeated    = _b(r["repeated_hint"])
        fp_meta     = _b(r["first_page_meta_like"])
        last_page   = _b(r["is_last_on_page"])

        char_count  = _f(r["char_count"])
        word_count  = _f(r["word_count"])
        sent_count  = _f(r["sentence_count"])
        punct_dens  = _f(r["punctuation_density"])
        digit_dens  = _f(r["digit_density"])
        ends_dot    = _b(r["ends_with_period"])
        ends_colon  = _b(r["ends_with_colon"])
        short_line  = _b(r["is_short_line"])
        has_doi     = _b(r["contains_doi"])
        has_year    = _b(r["contains_year"])
        has_cit_br  = _b(r["contains_citation_bracket"])
        has_cit_ay  = _b(r["contains_citation_author_year"])
        has_chap_num = _b(r["contains_chapter_number"])
        is_fig      = _b(r["is_figure_marker"])
        is_tbl      = _b(r["is_table_marker"])
        is_ref_hdr  = _b(r["is_references_marker"])

        cont_like   = _f(r["continuation_like"])
        in_flow     = _f(r["in_flow_score"])
        para_gap    = r["paragraph_gap_before"]
        in_column   = (1.0 if (para_gap is not None
                                and _f(para_gap) < 0
                                and _f(para_gap) > -50.0)
                       else 0.0)

        front_score = _f(r["front_matter_score"])
        body_score  = _f(r["body_score"])
        back_score  = _f(r["back_matter_score"])

        # ── Derived composite gates ───────────────────────────────────────

        sub_body_penalty = fnot(flinear(font_pct, 0.0, 0.25))
        typo_strong = fdampen(
            for_(bold, flinear(font_ratio, 1.05, 1.30)),
            fscale(sub_body_penalty, 0.90),
        )

        font_jump = for_(
            larger_prev,
            flinear(delta_prev, 1.0, 4.0),
        )

        not_repeated   = fnot(repeated)
        not_in_column  = fnot(in_column)

        # ── title_like ────────────────────────────────────────────────────
        top_font_tier = flinear(font_pct, 0.82, 1.0)
        truly_largest = for_(
            largest,
            fand(
                fp_meta,
                flinear(font_pct, 0.90, 1.0),
            ),
        )
        layout_support = for_(
            fscale(centered,  0.70),
            fscale(align_ctr, 0.65),
            fscale(fand(full_wide, typo_strong), 0.60),
        )
        words_short = flinear(18.0 - min(word_count, 18.0), 0.0, 18.0)
        title_form = fand(fnot(ends_dot), words_short)
        title_context = for_(fp_meta, fscale(front_score, 0.70))
        title_like = fand(
            truly_largest,
            for_(truly_largest, fscale(layout_support, 0.80)),
            title_form,
            not_repeated,
            fboost(title_context, 0.20),
        )

        # ── heading_like ──────────────────────────────────────────────────
        heading_font_zone = fand(
            flinear(font_pct, 0.65, 0.85),
            fnot(top_font_tier),
        )
        color_gate = for_(top_font_tier, fscale(typo_strong, 0.70), fscale(float(bold), 0.60))
        color_signal = (
            fscale(color_gate, 0.85) if color_rank == 1 else
            fscale(color_gate, 0.50) if color_rank >= 2 else
            0.0
        )
        typo_distinct = for_(
            fscale(heading_font_zone, 0.90),
            fscale(typo_strong,       0.80),
            fscale(font_jump,         0.85),
            fscale(all_caps,          0.60),
            fscale(letter_spaced,     0.55),
            fscale(larger_next,       0.40),
            color_signal,
        )
        heading_form = for_(
            fand(short_line, not_in_column),
            ends_colon,
            fscale(full_wide, 0.40),
            fscale(letter_spaced, 0.70),
            fscale(fand(bold, flinear(font_ratio, 1.05, 1.40),
                        fnot(flinear(word_count, 8, 20))), 0.65),
        )
        no_sentence = fnot(fand(ends_dot, flinear(word_count, 5, 12)))
        heading_like = fand(
            typo_distinct,
            heading_form,
            no_sentence,
            not_repeated,
            fdampen(1.0, fscale(cont_like, 0.80)),
        )

        if has_chap_num and typo_distinct > 0.10:
            heading_like = fboost(heading_like, 0.25)

        bold_large_font = (
            bold > 0.5
            and font_ratio > 1.10
            and word_count <= 8
            and typo_distinct > 0.10
            and not_repeated > 0.5
        )
        if bold_large_font:
            heading_like = fboost(heading_like, 0.35)

        # ── body_like ─────────────────────────────────────────────────────
        length_signal = for_(
            flinear(char_count, 60, 200),
            flinear(word_count, 12, 40),
        )
        sentence_signal = for_(
            ends_dot,
            flinear(sent_count, 1, 3),
        )
        flow_signal = for_(
            fscale(cont_like, 0.90),
            in_column,
        )
        body_like = for_(
            fand(length_signal, sentence_signal),
            fscale(flow_signal, 0.85),
            fscale(body_score,  0.70),
        )
        body_like = fdampen(body_like, fscale(repeated, 0.80))
        # Extreme font_ratio (>5x body) indicates a decorative/graphic element.
        # These blocks are not reliable body text — dampen body_like strongly.
        if font_ratio > 5.0:
            body_like = fdampen(body_like, 0.80)
        if letter_spaced:
            body_like = fscale(body_like, 0.15)

        # ── author_like ───────────────────────────────────────────────────
        name_gate  = _name_signal(text)
        positional = fand(short_line, fnot(ends_dot), fnot(has_doi))
        ctx_sup    = for_(fp_meta, fscale(front_score, 0.60))
        author_like = fguard(
            for_(positional, fscale(ctx_sup, 0.70)),
            name_gate,
        )

        # ── reference_like ────────────────────────────────────────────────
        long_enough = flinear(word_count, 6, 15)
        ref_explicit = for_(is_ref_hdr, fscale(has_doi, 0.90))
        ref_soft = for_(
            fscale(has_cit_br,  0.70),
            fscale(has_cit_ay,  0.70),
            fscale(fand(has_year, long_enough), 0.35),
            fscale(back_score,  0.60),
            fscale(flinear(punct_dens, 0.06, 0.15), 0.35),
            fscale(italic,      0.30),
        )
        reference_like = for_(ref_explicit, fscale(ref_soft, fboost(long_enough, 0.30)))

        # ── caption_like ──────────────────────────────────────────────────
        tl = text.lower()
        caption_prefix = 1.0 if any(tl.startswith(p) for p in (
            "figure ", "fig. ", "fig ", "table ", "tab. ",
            "abb. ", "abbildung ", "tabelle ", "plate ",
            "image ", "photo ", "grafik ", "karte ", "tafel ",
        )) else 0.0
        toc_dots = 1.0 if (text.count(".") >= 4 and text[-1:].isdigit()) else 0.0

        near_image_caption = fscale(near_image, 0.80) * (1.0 - min(1.0, typo_strong))
        caption_like = for_(
            fscale(for_(is_fig, is_tbl), 0.95),
            fscale(caption_prefix, 0.90),
            fscale(toc_dots, 0.85),
            fscale(fand(narrow, fand(ends_dot, fnot(_b(r["starts_with_number"])))), 0.50),
            fscale(fand(italic, narrow), 0.40),
            near_image_caption,
        )

        near_image_dampen = fscale(near_image, 0.95) * (1.0 - min(1.0, typo_strong))
        heading_like = fdampen(heading_like, near_image_dampen)
        heading_like = fdampen(heading_like, fscale(float(in_colored_box), 0.70))

        if narrow and font_pct < 0.65:
            heading_like = fand(heading_like, flinear(in_flow, 0.0, 0.50))

        # ── noise_like ────────────────────────────────────────────────────
        tiny = 1.0 if char_count <= 2 else 0.0
        short_last = fand(last_page, flinear(30.0 - min(char_count, 30.0), 0.0, 30.0))
        noise_like = for_(
            fscale(repeated,  0.90),
            fscale(short_last, 0.50),
            fscale(fand(narrow, tiny), 0.60),
            fscale(flinear(digit_dens, 0.50, 1.0), 0.40),
        )

        signal_rows.append((
            r["block_id"],
            max(0.0, title_like),
            max(0.0, heading_like),
            max(0.0, body_like),
            max(0.0, author_like),
            max(0.0, reference_like),
            max(0.0, caption_like),
            max(0.0, noise_like),
        ))

    conn.executemany(
        """
        INSERT INTO du_block_signals (
            block_id,
            title_like, heading_like, body_like, author_like,
            reference_like, caption_like, noise_like
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT (block_id) DO UPDATE SET
            title_like     = excluded.title_like,
            heading_like   = excluded.heading_like,
            body_like      = excluded.body_like,
            author_like    = excluded.author_like,
            reference_like = excluded.reference_like,
            caption_like   = excluded.caption_like,
            noise_like     = excluded.noise_like
        """,
        signal_rows,
    )
    conn.commit()
