from __future__ import annotations

import re

from atlas.db.connection import get_connection


BAD_SUBSTRINGS = (
    "tag der disputation",
    "tag der mündlichen prüfung",
    "zweiter gutachter",
    "journal director",
    "tel.:",
    "fax:",
    "doi",
    "issn",
    "isbn",
    "www.",
    "http://",
    "https://",
    "grafik:",
    "foto:",
    "zur gedruckten ausgabe",
    "conclusion:",
    "abstract",
    "contents",
    "inhalt",
)

BAD_LINE_PATTERNS = (
    r"^prof\.",
    r"^dr\.",
    r"^universität",
    r"^technische universität",
    r"^eingereicht",
    r"^dissertation",
    r"^thesis",
    r"^chapter\b",
    r"^figure\b",
    r"^abb\.",
    r"^tab\.",
    r"^proc[a-z]",
    r"^\d+\s*$",
    r"^[\W\d_]+$",
)


def _clean_line(line: str) -> str:
    line = line.replace("\x00", "").strip()
    line = re.sub(r"\s+", " ", line)
    return line


def _looks_like_sentence(line: str) -> bool:
    if len(line) < 20:
        return False
    if line.endswith("."):
        return True
    lower = line.lower()
    return any(
        phrase in lower
        for phrase in (
            " this ",
            " that ",
            " are ",
            " is ",
            " was ",
            " were ",
            " were ",
            " mit ",
            " und ",
            " der ",
            " die ",
            " das ",
            " ein ",
            " eine ",
        )
    )


def _looks_like_bad_title(line: str) -> bool:
    if not line:
        return True
    if len(line) < 8:
        return True
    if len(line) > 180:
        return True

    lower = line.lower()

    if any(substr in lower for substr in BAD_SUBSTRINGS):
        return True

    if any(re.search(pattern, lower) for pattern in BAD_LINE_PATTERNS):
        return True

    if re.fullmatch(r"[\d\s\W_]+", line):
        return True

    if _looks_like_sentence(line):
        return True

    alpha_count = sum(1 for c in line if c.isalpha())
    if alpha_count == 0:
        return True

    uppercase_ratio = sum(1 for c in line if c.isupper()) / max(1, alpha_count)
    if uppercase_ratio > 0.85 and len(line.split()) > 8:
        return True

    return False


def _score_title_candidate(line: str, position: int) -> float:
    score = 0.0
    length = len(line)
    words = line.split()

    if 20 <= length <= 120:
        score += 3.0
    elif 12 <= length <= 150:
        score += 1.5
    else:
        score -= 1.0

    if 3 <= len(words) <= 16:
        score += 2.0
    elif len(words) > 22:
        score -= 2.0

    if not line.endswith("."):
        score += 1.0

    if ":" in line:
        score += 0.3

    if any(c.isalpha() for c in line):
        score += 1.0

    alpha_count = sum(1 for c in line if c.isalpha())
    uppercase_ratio = sum(1 for c in line if c.isupper()) / max(1, alpha_count)
    if 0.05 <= uppercase_ratio <= 0.45:
        score += 1.0

    # frühe Zeilen bevorzugen
    score += max(0, 3.0 - (position * 0.15))

    return score


def guess_title_from_text(text: str | None) -> str | None:
    if not text:
        return None

    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    candidates = lines[:40]
    best_line = None
    best_score = float("-inf")

    for idx, line in enumerate(candidates):
        if _looks_like_bad_title(line):
            continue

        score = _score_title_candidate(line, idx)

        if score > best_score:
            best_score = score
            best_line = line

    return best_line


def enrich_titles() -> int:
    updated = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select d.document_id, e.text_full
                from documents d
                join lateral (
                    select text_full
                    from extracted_texts
                    where document_id = d.document_id
                      and extract_status = 'ok'
                    order by created_at desc
                    limit 1
                ) e on true
                where d.title is null
                """
            )
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for document_id, text_full in rows:
                title = guess_title_from_text(text_full)
                if title:
                    cur.execute(
                        """
                        update documents
                        set title = %s,
                            title_source = 'heuristic_first_lines_v2'
                        where document_id = %s
                        """,
                        (title, document_id),
                    )
                    updated += 1

    return updated
