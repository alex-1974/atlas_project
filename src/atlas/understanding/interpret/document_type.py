# src/atlas/understanding/interpret/document_type.py
"""Layer 3 — document type classification with probability distribution.

Architecture
------------
Each document type is a DocumentTypeProfile subclass in _REGISTRY.
The classifier produces a probability vector over all types — not a
single hard label. This reflects that many documents span multiple
categories (e.g. a scanned historical journal article is both
'article' and 'archival').

Storage
-------
documents.du_document_type        TEXT  — primary type (highest weight)
documents.du_document_type_scores TEXT  — JSON: {"article": 0.65, ...}

Signal adjustment
-----------------
adjust_block_scores() is called with a weight parameter (0–1).
Each profile scales its adjustments by its weight, so multiple
profiles contribute proportionally.

Type hierarchy (Stufe 1 — layout-detectable)
--------------------------------------------
  article       — journal article, conference paper, essay, working paper
  monograph     — book, textbook, reference work
  thesis        — dissertation, master thesis, habilitation
  report        — technical report, guidance document, working paper
  archival      — scanned historical document, irregular typography
  presentation  — slide deck PDF export

Stufe 2 subtypes (content-based, Phase 2/3):
  article    -> journal_article | conference_paper | essay | working_paper
  monograph  -> scientific | textbook | narrative | reference
  thesis     -> dissertation | master | habilitation

Adding a new type
-----------------
1. Subclass DocumentTypeProfile
2. Implement score() and adjust_block_scores()
3. Add an instance to _REGISTRY
Nothing else changes.
"""
from __future__ import annotations

from atlas.core.logging import get_logger
_log = get_logger("atlas.du.document_type")

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass


# BlockScores

@dataclass
class BlockScores:
    title_like:     float
    heading_like:   float
    body_like:      float
    author_like:    float
    reference_like: float
    caption_like:   float
    noise_like:     float

    def clamp(self) -> None:
        for field in self.__dataclass_fields__:
            setattr(self, field, max(0.0, getattr(self, field)))


# Base class

class DocumentTypeProfile(ABC):

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def score(self, meta: dict) -> float: ...

    def adjust_block_scores(
        self, block: dict, scores: BlockScores, weight: float = 1.0
    ) -> BlockScores:
        return scores


# Profiles

class ArticleProfile(DocumentTypeProfile):
    @property
    def name(self) -> str: return "article"

    def score(self, meta: dict) -> float:
        s = 0.0
        if meta.get("doi_count", 0) >= 1:           s += 0.40
        if meta.get("strong_journal_header"):        s += 0.35
        if meta.get("very_strong_journal_header"):   s += 0.15
        if meta.get("has_abstract"):                 s += 0.25
        if meta.get("has_references"):               s += 0.15
        if meta.get("two_column_hint"):              s += 0.30
        if meta.get("has_keywords"):                 s += 0.10
        pages = meta.get("page_count", 999)
        if pages <= 60:                              s += 0.10
        # Short doc without TOC and without thesis markers: likely article
        if pages <= 30 and not meta.get("has_toc") and not meta.get("strong_thesis_header"):
                                                     s += 0.15
        if (meta.get("two_column_hint")
                and pages <= 30
                and not meta.get("has_toc")):        s += 0.25
        if meta.get("strong_thesis_header"):         s -= 0.35
        if meta.get("has_toc"):                      s -= 0.15
        if pages > 100:                              s -= 0.25
        return max(0.0, s)

    def adjust_block_scores(self, block, scores, weight=1.0):
        in_col = block.get("in_column_context", False)
        bold_or_large = block.get("bold_or_large", False)
        if in_col and not bold_or_large:
            scores.heading_like = max(0.0, scores.heading_like - 0.15 * weight)
            scores.title_like   = max(0.0, scores.title_like   - 0.15 * weight)
            scores.body_like   += 0.10 * weight
        return scores


class MonographProfile(DocumentTypeProfile):
    @property
    def name(self) -> str: return "monograph"

    def score(self, meta: dict) -> float:
        s = 0.0
        pages = meta.get("page_count", 0)
        depth = meta.get("heading_depth", 0)

        # TOC + substantial length is a monograph signal.
        # Reports and guidance documents also have TOCs, so require
        # page_count > 80 to distinguish.
        if meta.get("has_toc") and pages > 80:       s += 0.40
        elif meta.get("has_toc"):                    s += 0.10  # weak signal alone

        if pages > 80:                               s += 0.25

        # Deep heading hierarchy is a monograph indicator, but only
        # when combined with substantial length — reports can have L3 too.
        if depth >= 4 and pages > 80:                s += 0.20
        elif depth >= 4:                             s += 0.10
        elif depth >= 3 and pages > 150:             s += 0.10

        if meta.get("single_column_hint"):           s += 0.15
        if not meta.get("has_abstract"):             s += 0.10
        if not meta.get("doi_count", 0):             s += 0.10
        if pages > 200:                              s += 0.15
        if meta.get("strong_journal_header"):        s -= 0.30
        if meta.get("strong_thesis_header"):         s -= 0.15
        if meta.get("two_column_hint"):              s -= 0.10
        # Section explosion: glossaries/dictionaries have many short sections
        # per page — not a typical monograph structure
        if meta.get("sections_per_page", 0) > 2:    s -= 0.30
        return max(0.0, s)

    def adjust_block_scores(self, block, scores, weight=1.0):
        scores.heading_like += 0.05 * weight
        return scores


class ThesisProfile(DocumentTypeProfile):
    @property
    def name(self) -> str: return "thesis"

    def score(self, meta: dict) -> float:
        s = 0.0
        has_thesis = meta.get("strong_thesis_header", False)
        has_abs    = meta.get("has_abstract", False)
        univ       = meta.get("university_marker_count", 0)
        supervisor = meta.get("supervisor_marker_count", 0)

        if has_thesis:                               s += 0.55
        if supervisor >= 1:                          s += 0.20
        # University alone is a weak signal — many non-thesis documents
        # (exhibition catalogues, institutional reports, lecture notes)
        # contain university names. Only score when combined with
        # corroborating evidence.
        if univ >= 2 and (has_thesis or has_abs or supervisor >= 1):
                                                     s += 0.20
        if meta.get("has_toc"):                      s += 0.20
        if meta.get("page_count", 0) > 80:           s += 0.15
        if has_abs:                                  s += 0.10
        if meta.get("strong_journal_header"):        s -= 0.35
        if meta.get("doi_count", 0) >= 1 and not has_thesis:
                                                     s -= 0.10
        # Section explosion is not consistent with thesis structure
        if meta.get("sections_per_page", 0) > 2:    s -= 0.40
        return max(0.0, s)


class ReportProfile(DocumentTypeProfile):
    @property
    def name(self) -> str: return "report"

    def score(self, meta: dict) -> float:
        s = 0.0
        if meta.get("report_marker_count", 0) >= 1: s += 0.40
        if meta.get("has_toc"):                      s += 0.20
        if meta.get("single_column_hint"):           s += 0.15
        if not meta.get("strong_journal_header"):    s += 0.10
        if not meta.get("strong_thesis_header"):     s += 0.05
        if meta.get("doi_count", 0) >= 1:            s -= 0.15
        if meta.get("strong_journal_header"):        s -= 0.30
        if meta.get("two_column_hint"):              s -= 0.10
        return max(0.0, s)


class ArchivalProfile(DocumentTypeProfile):
    @property
    def name(self) -> str: return "archival"

    def score(self, meta: dict) -> float:
        s = 0.0
        if meta.get("is_image_pdf"):                 s += 0.50
        if meta.get("high_noise_ratio"):             s += 0.30
        if meta.get("mixed_text_source"):            s += 0.20
        if not meta.get("doi_count", 0):             s += 0.10
        if meta.get("doi_count", 0) >= 1:            s -= 0.25
        if meta.get("strong_journal_header"):        s -= 0.15
        return max(0.0, s)

    def adjust_block_scores(self, block, scores, weight=1.0):
        scores.noise_like = max(0.0, scores.noise_like - 0.15 * weight)
        scores.body_like += 0.05 * weight
        return scores


class PresentationProfile(DocumentTypeProfile):
    @property
    def name(self) -> str: return "presentation"

    def score(self, meta: dict) -> float:
        s = 0.0
        if meta.get("high_title_ratio"):             s += 0.45
        if meta.get("low_words_per_page"):           s += 0.35
        if not meta.get("has_references"):           s += 0.10
        if not meta.get("has_abstract"):             s += 0.05
        if meta.get("doi_count", 0) >= 1:            s -= 0.25
        if meta.get("strong_journal_header"):        s -= 0.30
        if meta.get("two_column_hint"):              s -= 0.60
        if meta.get("has_toc"):                      s -= 0.15
        return max(0.0, s)

    def adjust_block_scores(self, block, scores, weight=1.0):
        scores.heading_like += 0.10 * weight
        scores.body_like     = max(0.0, scores.body_like - 0.10 * weight)
        return scores


# Registry

_REGISTRY: list[DocumentTypeProfile] = [
    ArticleProfile(),
    MonographProfile(),
    ThesisProfile(),
    ReportProfile(),
    ArchivalProfile(),
    PresentationProfile(),
]

UNKNOWN_TYPE   = "unknown"
_MIN_TOTAL_SCORE = 0.10
_MIN_WEIGHT      = 0.10


def get_profile(type_name: str | None) -> DocumentTypeProfile | None:
    if not type_name:
        return None
    for p in _REGISTRY:
        if p.name == type_name:
            return p
    return None


def registered_types() -> list[str]:
    return [p.name for p in _REGISTRY]


def get_type_scores(type_scores_json: str | None) -> dict[str, float]:
    if not type_scores_json:
        return {}
    try:
        return json.loads(type_scores_json)
    except (json.JSONDecodeError, TypeError):
        return {}


# Meta-feature extraction

def _build_meta(conn: sqlite3.Connection, document_id: str) -> dict:
    from atlas.understanding.interpret.early_meta import detect_early_meta_signals
    from atlas.understanding.core.section_labels import (
        ABSTRACT_HEADINGS, TOC_HEADINGS, REFERENCE_HEADINGS, KEYWORDS_HEADINGS,
    )

    blocks_raw = conn.execute(
        "SELECT text FROM du_blocks WHERE document_id = ? ORDER BY block_index LIMIT 6",
        (document_id,),
    ).fetchall()
    early_meta = detect_early_meta_signals([dict(r) for r in blocks_raw])

    page_count = conn.execute(
        "SELECT COUNT(*) FROM du_pages WHERE document_id = ?", (document_id,)
    ).fetchone()[0]

    heading_texts = {
        r[0].strip().lower()
        for r in conn.execute(
            """SELECT DISTINCT substr(lower(b.text), 1, 60)
               FROM du_blocks b JOIN du_block_roles r ON r.block_id = b.block_id
               WHERE b.document_id = ? AND r.role IN ('heading', 'reference')""",
            (document_id,),
        ).fetchall() if r[0]
    }

    has_abstract   = any(t in ABSTRACT_HEADINGS   for t in heading_texts)
    has_toc        = any(t in TOC_HEADINGS         for t in heading_texts)
    has_references = any(t in REFERENCE_HEADINGS   for t in heading_texts)
    has_keywords   = any(t in KEYWORDS_HEADINGS    for t in heading_texts)

    heading_depth = conn.execute(
        "SELECT COALESCE(MAX(level), 0) FROM du_section_tree WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    section_count = conn.execute(
        "SELECT COUNT(*) FROM du_section_tree WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    # sections_per_page > 2 indicates a glossary, index, or dictionary —
    # not a typical monograph or thesis chapter structure
    sections_per_page = section_count / max(1, page_count)

    total_blocks = conn.execute(
        "SELECT COUNT(*) FROM du_blocks WHERE document_id = ?", (document_id,)
    ).fetchone()[0] or 1

    col_rows = conn.execute(
        """SELECT COUNT(*) FROM du_block_spacing sp
           JOIN du_blocks b ON b.block_id = sp.block_id
           WHERE b.document_id = ? AND sp.paragraph_gap_before < 0""",
        (document_id,),
    ).fetchone()[0]
    two_column_hint    = (col_rows / total_blocks) > 0.25
    single_column_hint = (col_rows / total_blocks) < 0.05

    noise_rows = conn.execute(
        """SELECT COUNT(*) FROM du_block_roles r
           JOIN du_blocks b ON b.block_id = r.block_id
           WHERE b.document_id = ? AND r.role = 'noise'""",
        (document_id,),
    ).fetchone()[0]
    high_noise_ratio = (noise_rows / total_blocks) > 0.20

    title_rows = conn.execute(
        """SELECT COUNT(*) FROM du_block_roles r
           JOIN du_blocks b ON b.block_id = r.block_id
           WHERE b.document_id = ? AND r.role = 'title'""",
        (document_id,),
    ).fetchone()[0]
    high_title_ratio = (title_rows / total_blocks) > 0.15

    words_row = conn.execute(
        """SELECT COALESCE(SUM(sf.word_count), 0)
           FROM du_block_surface sf JOIN du_blocks b ON b.block_id = sf.block_id
           WHERE b.document_id = ?""",
        (document_id,),
    ).fetchone()[0]
    words_per_page     = words_row / max(1, page_count)
    low_words_per_page = words_per_page < 120

    src_row = conn.execute(
        "SELECT text_source FROM du_documents WHERE document_id = ?", (document_id,)
    ).fetchone()
    is_image_pdf      = bool(src_row and src_row[0] == "ocr")
    mixed_text_source = bool(src_row and src_row[0] == "mixed")

    return {
        **early_meta,
        "page_count":          page_count,
        "has_abstract":        has_abstract,
        "has_toc":             has_toc,
        "has_references":      has_references,
        "has_keywords":        has_keywords,
        "heading_depth":       heading_depth,
        "section_count":       section_count,
        "sections_per_page":   sections_per_page,
        "two_column_hint":     two_column_hint,
        "single_column_hint":  single_column_hint,
        "high_noise_ratio":    high_noise_ratio,
        "high_title_ratio":    high_title_ratio,
        "low_words_per_page":  low_words_per_page,
        "is_image_pdf":        is_image_pdf,
        "mixed_text_source":   mixed_text_source,
    }


def _normalise(raw: dict[str, float]) -> dict[str, float]:
    total = sum(raw.values())
    if total < _MIN_TOTAL_SCORE:
        return {}
    return {k: round(v / total, 4) for k, v in raw.items() if v > 0}


# Public API

def compute_document_type(conn: sqlite3.Connection, document_id: str) -> str:
    """Compute probability distribution over document types.

    Writes du_document_type (primary) and du_document_type_scores (JSON vector).
    """
    meta = _build_meta(conn, document_id)
    raw  = {p.name: p.score(meta) for p in _REGISTRY}
    _log.debug("document_type doc=%s scores=%s", document_id[:12],
               {k: round(v, 3) for k, v in raw.items()})
    normalised = _normalise(raw)

    if not normalised:
        primary     = UNKNOWN_TYPE
        scores_json = json.dumps({})
    else:
        primary     = max(normalised, key=normalised.__getitem__)
        scores_json = json.dumps(normalised)

    conn.execute(
        "UPDATE documents SET du_document_type = ?, du_document_type_scores = ? "
        "WHERE document_id = ?",
        (primary, scores_json, document_id),
    )
    conn.commit()
    return primary


def apply_type_adjustments(
    block: dict,
    scores: BlockScores,
    type_scores_json: str | None,
) -> BlockScores:
    """Apply weighted adjustments from all active profiles.

    Called from roles.py. Each profile contributes in proportion to its
    probability weight. Profiles below _MIN_WEIGHT are skipped.
    """
    weights = get_type_scores(type_scores_json)
    if not weights:
        return scores
    for profile in _REGISTRY:
        weight = weights.get(profile.name, 0.0)
        if weight >= _MIN_WEIGHT:
            scores = profile.adjust_block_scores(block, scores, weight=weight)
    return scores
