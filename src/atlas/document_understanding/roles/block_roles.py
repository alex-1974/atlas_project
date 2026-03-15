from __future__ import annotations

import re
from typing import Dict, List

from atlas.document_understanding.persistence.repository import DURepository
from atlas.document_understanding.grammar.role_bias import apply_role_bias
from atlas.document_understanding.grammar.document_type import infer_document_type


KEYWORDS_RE = re.compile(
    r"^(keywords?|key words|schlagwörter|schlüsselwörter)\b",
    re.IGNORECASE,
)

ABSTRACT_RE = re.compile(
    r"^(abstract|zusammenfassung|summary|résumé)\b",
    re.IGNORECASE,
)

FIGURE_RE = re.compile(
    r"^(fig\.?|figure|abb\.?|abbildung)\b",
    re.IGNORECASE,
)

TABLE_RE = re.compile(
    r"^(table|tab\.?|tabelle)\b",
    re.IGNORECASE,
)

APPENDIX_RE = re.compile(
    r"^(appendix|appendices|anhang)\b",
    re.IGNORECASE,
)


def fetch_role_block_map(repo: DURepository, document_id: str) -> list[dict]:
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            select
                b.block_id,
                b.block_index,
                b.page_index,
                b.text,

                coalesce(s.title_like, 0.0) as title_like,
                coalesce(s.author_like, 0.0) as author_like,
                coalesce(s.affiliation_like, 0.0) as affiliation_like,
                coalesce(s.date_like, 0.0) as date_like,
                coalesce(s.running_text_like, 0.0) as running_text_like,
                coalesce(s.heading_like, 0.0) as heading_like,
                coalesce(s.list_like, 0.0) as list_like,
                coalesce(s.toc_like, 0.0) as toc_like,
                coalesce(s.reference_like, 0.0) as reference_like,
                coalesce(s.bibliographic_entry_like, 0.0) as bibliographic_entry_like,
                coalesce(s.caption_like, 0.0) as caption_like,
                coalesce(s.marker_like, 0.0) as marker_like,
                coalesce(s.parenthetical_citation_like, 0.0) as parenthetical_citation_like,
                coalesce(s.journal_meta_like, 0.0) as journal_meta_like,
                coalesce(s.artifact_like, 0.0) as artifact_like,
                coalesce(s.map_label_like, 0.0) as map_label_like,
                coalesce(s.noise_like, 0.0) as noise_like,

                coalesce(g.whitespace_before, 0.0) as whitespace_before,
                coalesce(g.whitespace_after, 0.0) as whitespace_after,
                coalesce(g.centeredness, 0.0) as centeredness,
                coalesce(g.near_page_top, 0.0) as near_page_top,
                coalesce(g.near_page_bottom, 0.0) as near_page_bottom,

                coalesce(t.is_first_on_page, false) as is_first_on_page,
                coalesce(t.is_last_on_page, false) as is_last_on_page,
                coalesce(t.early_block_rank, b.block_index) as early_block_rank
            from du_blocks b
            left join du_block_signals s on s.block_id = b.block_id
            left join du_block_geometry g on g.block_id = b.block_id
            left join du_block_topology t on t.block_id = b.block_id
            where b.document_id = %s
            order by b.block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _text(block: dict) -> str:
    return (block.get("text") or "").strip()


def _word_count(block: dict) -> int:
    text = _text(block)
    return len(text.split()) if text else 0


def _is_short(block: dict, max_words: int = 12) -> bool:
    return _word_count(block) <= max_words


def _role_scores(block: dict) -> Dict[str, float]:
    text = _text(block)
    lower = text.lower()

    scores: Dict[str, float] = {
        "title_line": 0.0,
        "author_line": 0.0,
        "abstract_heading": 0.0,
        "abstract_text": 0.0,
        "keyword_line": 0.0,
        "section_heading": 0.0,
        "body_text": 0.0,
        "reference_entry": 0.0,
        "caption": 0.0,
        "appendix_heading": 0.0,
        "other": 0.0,
    }

    short = _is_short(block)
    near_top = float(block["near_page_top"])
    centered = float(block["centeredness"])
    heading_like = float(block["heading_like"])
    running = float(block["running_text_like"])
    reference = float(block["reference_like"])
    toc_like = float(block["toc_like"])
    caption_like = float(block["caption_like"])
    title_like = float(block["title_like"])
    author_like = float(block["author_like"])
    whitespace_before = float(block["whitespace_before"])

    scores["title_line"] = (
        1.8 * title_like
        + 1.0 * centered
        + 0.8 * near_top
        + 0.4 * float(short)
        - 0.8 * running
        - 0.6 * reference
    )

    scores["author_line"] = (
        1.8 * author_like
        + 0.5 * centered
        + 0.5 * near_top
        - 0.5 * running
        - 0.4 * reference
    )

    scores["abstract_heading"] = (
        1.5 * float(bool(ABSTRACT_RE.match(lower)))
        + 0.8 * heading_like
        + 0.3 * near_top
        - 0.5 * running
    )

    scores["abstract_text"] = (
        1.5 * running
        + 0.2 * near_top
        - 0.7 * reference
        - 0.6 * toc_like
        - 0.5 * float(short)
    )

    scores["keyword_line"] = (
        2.0 * float(bool(KEYWORDS_RE.match(lower)))
        + 0.2 * near_top
        - 0.4 * reference
    )

    scores["section_heading"] = (
        1.6 * heading_like
        + 0.3 * whitespace_before
        + 0.3 * float(short)
        - 0.7 * running
        - 0.4 * reference
        - 0.3 * toc_like
    )

    scores["body_text"] = (
        1.8 * running
        - 0.8 * heading_like
        - 0.6 * reference
        - 0.5 * caption_like
        - 0.5 * toc_like
    )

    scores["reference_entry"] = (
        1.8 * reference
        + 0.8 * float(block["bibliographic_entry_like"])
        + 0.4 * float(block["parenthetical_citation_like"])
        - 0.5 * heading_like
    )

    scores["caption"] = (
        1.8 * caption_like
        + 1.2 * float(bool(FIGURE_RE.match(lower) or TABLE_RE.match(lower)))
        + 0.3 * float(short)
        - 0.4 * running
    )

    scores["appendix_heading"] = (
        2.0 * float(bool(APPENDIX_RE.match(lower)))
        + 0.7 * heading_like
        + 0.2 * float(block["near_page_bottom"])
        - 0.5 * running
    )

    scores["other"] = (
        0.4 * float(block["noise_like"])
        + 0.3 * float(block["artifact_like"])
        + 0.2 * float(block["affiliation_like"])
        + 0.2 * float(block["journal_meta_like"])
    )

    return scores


def compute_block_roles(blocks: List[dict]) -> Dict[str, dict]:
    roles: Dict[str, dict] = {}

    for block in blocks:
        scores = _role_scores(block)
        best_role = max(scores, key=scores.get)

        roles[str(block["block_id"])] = {
            "role": best_role,
            "score": scores[best_role],
            "scores": scores,
        }

    return roles


def apply_context_correction(blocks: List[dict], roles: Dict[str, dict]) -> Dict[str, dict]:
    ordered = sorted(blocks, key=lambda b: b["block_index"])

    for i, block in enumerate(ordered):
        block_id = str(block["block_id"])
        current = roles[block_id]["role"]
        text = _text(block).lower()

        prev_role = None
        if i > 0:
            prev_role = roles[str(ordered[i - 1]["block_id"])]["role"]

        if prev_role == "abstract_heading" and current == "body_text":
            roles[block_id]["role"] = "abstract_text"

        if KEYWORDS_RE.match(text):
            roles[block_id]["role"] = "keyword_line"

        if APPENDIX_RE.match(text):
            roles[block_id]["role"] = "appendix_heading"

        if FIGURE_RE.match(text) or TABLE_RE.match(text):
            roles[block_id]["role"] = "caption"

        if (
            prev_role == "section_heading"
            and current == "body_text"
            and _is_short(block, max_words=8)
            and float(block["heading_like"]) > 0.3
        ):
            roles[block_id]["role"] = "section_heading"

        if (
            prev_role == "abstract_heading"
            and float(block["running_text_like"]) > 0.5
            and not KEYWORDS_RE.match(text)
        ):
            roles[block_id]["role"] = "abstract_text"

        if (
            prev_role == "title_line"
            and current == "section_heading"
            and float(block["author_like"]) > 0.3
            and block["page_index"] == 0
        ):
            roles[block_id]["role"] = "author_line"

    return roles


def compute_roles(blocks: List[dict]) -> Dict[str, dict]:

    document_type = infer_document_type(blocks)

    roles: Dict[str, dict] = {}

    for block in blocks:

        scores = _role_scores(block)

        scores = apply_role_bias(scores, document_type)

        best_role = max(scores, key=scores.get)

        roles[str(block["block_id"])] = {
            "role": best_role,
            "score": scores[best_role],
            "scores": scores,
        }

    roles = apply_context_correction(blocks, roles)

    return roles


def inspect_roles(repo: DURepository, document_id: str) -> list[dict]:
    blocks = fetch_role_block_map(repo, document_id)
    roles = compute_roles(blocks)

    rows = []
    for block in blocks:
        block_id = str(block["block_id"])
        role_info = roles[block_id]
        rows.append(
            {
                "block_index": block["block_index"],
                "page_index": block["page_index"],
                "role": role_info["role"],
                "score": role_info["score"],
                "text": _text(block),
            }
        )

    return rows
