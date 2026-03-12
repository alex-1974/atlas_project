from __future__ import annotations

import re

from atlas.document_understanding.persistence.repository import DURepository


YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://")
ET_AL_RE = re.compile(r"\bet al\.", re.IGNORECASE)

PAREN_CIT_RE = re.compile(r"\([A-Z][A-Za-z]+,?\s*\d{4}\)")

LIST_MARKER_RE = re.compile(r"^\s*[-•*]\s+")
NUMBERED_LIST_RE = re.compile(r"^\s*\d+\.\s+")

REFERENCE_PATTERN = re.compile(
    r"\b(doi|journal|vol\.?|pp\.?|isbn|issn)\b",
    re.IGNORECASE,
)


def compute_signals(repo: DURepository, document_id: str) -> None:

    blocks = fetch_blocks(repo, document_id)

    rows = []

    for block in blocks:

        text = block["text"]

        rows.append(
            {
                "block_id": block["block_id"],
                "title_like": score_title(text),
                "author_like": score_author(text),
                "affiliation_like": score_affiliation(text),
                "date_like": score_date(text),
                "running_text_like": score_running_text(text),
                "heading_like": score_heading(text),
                "list_like": score_list(text),
                "toc_like": score_toc(text),
                "reference_like": score_reference(text),
                "bibliographic_entry_like": score_bibliographic(text),
                "caption_like": score_caption(text),
                "marker_like": score_marker(text),
                "parenthetical_citation_like": score_parenthetical_citation(text),
                "journal_meta_like": score_journal_meta(text),
                "artifact_like": score_artifact(text),
                "noise_like": score_noise(text),
            }
        )

    insert_signals(repo, rows)


def fetch_blocks(repo: DURepository, document_id):

    with repo.conn.cursor() as cur:

        cur.execute(
            """
            select block_id, text
            from du_blocks
            where document_id = %s
            order by block_index
            """,
            (document_id,),
        )

        cols = [c.name for c in cur.description]

        return [dict(zip(cols, r)) for r in cur.fetchall()]


def insert_signals(repo: DURepository, rows):

    with repo.conn.cursor() as cur:

        for r in rows:

            cur.execute(
                """
                insert into du_block_signals (
                    block_id,
                    title_like,
                    author_like,
                    affiliation_like,
                    date_like,
                    running_text_like,
                    heading_like,
                    list_like,
                    toc_like,
                    reference_like,
                    bibliographic_entry_like,
                    caption_like,
                    marker_like,
                    parenthetical_citation_like,
                    journal_meta_like,
                    artifact_like,
                    noise_like
                )
                values (
                    %(block_id)s,
                    %(title_like)s,
                    %(author_like)s,
                    %(affiliation_like)s,
                    %(date_like)s,
                    %(running_text_like)s,
                    %(heading_like)s,
                    %(list_like)s,
                    %(toc_like)s,
                    %(reference_like)s,
                    %(bibliographic_entry_like)s,
                    %(caption_like)s,
                    %(marker_like)s,
                    %(parenthetical_citation_like)s,
                    %(journal_meta_like)s,
                    %(artifact_like)s,
                    %(noise_like)s
                )
                on conflict (block_id) do nothing
                """,
                r,
            )


# ---------------------------------------------------------
# Signal scoring functions
# ---------------------------------------------------------


def score_title(text: str) -> float:

    if len(text) < 15:
        return 0.0

    if text.isupper():
        return 0.8

    if text.istitle():
        return 0.6

    if len(text) < 120:
        return 0.3

    return 0.0


def score_author(text: str) -> float:

    if " and " in text.lower():
        return 0.4

    if "," in text and len(text.split()) <= 6:
        return 0.5

    return 0.0


def score_affiliation(text: str) -> float:

    keywords = ["university", "institute", "department", "faculty"]

    for k in keywords:
        if k in text.lower():
            return 0.6

    return 0.0


def score_date(text: str) -> float:

    if YEAR_RE.search(text):
        return 0.5

    return 0.0


def score_running_text(text: str) -> float:

    words = text.split()

    if len(words) > 20:
        return 0.8

    if len(words) > 10:
        return 0.4

    return 0.0


def score_heading(text: str) -> float:

    if len(text.split()) < 10 and text.endswith(":"):
        return 0.6

    if len(text.split()) < 8:
        return 0.3

    return 0.0


def score_list(text: str) -> float:

    if LIST_MARKER_RE.match(text):
        return 0.8

    if NUMBERED_LIST_RE.match(text):
        return 0.8

    return 0.0


def score_toc(text: str) -> float:

    if "..." in text or "...." in text:
        return 0.7

    if re.search(r"\s\d{1,3}$", text):
        return 0.5

    return 0.0


def score_reference(text: str) -> float:

    if DOI_RE.search(text):
        return 0.8

    if REFERENCE_PATTERN.search(text):
        return 0.6

    return 0.0


def score_bibliographic(text: str) -> float:

    if YEAR_RE.search(text) and "," in text:
        return 0.5

    return 0.0


def score_caption(text: str) -> float:

    if text.lower().startswith("figure"):
        return 0.7

    if text.lower().startswith("fig."):
        return 0.7

    return 0.0


def score_marker(text: str) -> float:

    if text.strip().isdigit():
        return 0.4

    return 0.0


def score_parenthetical_citation(text: str) -> float:

    if PAREN_CIT_RE.search(text):
        return 0.8

    return 0.0


def score_journal_meta(text: str) -> float:

    if "vol." in text.lower() or "issue" in text.lower():
        return 0.6

    return 0.0


def score_artifact(text: str) -> float:

    if len(text.strip()) < 3:
        return 0.8

    return 0.0


def score_noise(text: str) -> float:

    if text.count(" ") == 0 and len(text) > 30:
        return 0.7

    return 0.0
