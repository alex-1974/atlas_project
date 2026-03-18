from __future__ import annotations

import re

from atlas.db.connection import get_connection
from atlas.structure.header_candidates import extract_header_candidates
from atlas.structure.document_kind import score_document_kind


MAX_CANDIDATE_LINES = 12
MAX_SCAN_LINES = 40
MAX_TITLE_LENGTH = 220

UPPERCASE_RE = re.compile(r"[A-ZÄÖÜ]")
LOWERCASE_RE = re.compile(r"[a-zäöü]")
YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
ENUM_RE = re.compile(r"^\s*\d+(\.\d+)*\s*")

BY_RE = re.compile(r"\s+(by|von|par|por)\s+", re.I)

PAGE_RE = re.compile(
    r"\b(page|pages|seite|seiten|band|vol\.?|volume|nr\.?|no\.?|issue|pp\.?|issn|isbn|serial)\b",
    re.I,
)

ADMIN_RE = re.compile(
    r"\b(abstract|introduction|contents|bibliography|references|"
    r"inhaltsverzeichnis|literatur|literaturverzeichnis|summary|"
    r"keywords?|schlagw[oö]rter|einleitung)\b",
    re.I,
)

META_RE = re.compile(
    r"\b(editor|editors|director|special editors?|journal director|"
    r"betreuer|gutachter|erstgutachter|zweitgutachter|submitted|"
    r"vorgelegt|universität|university|department|institut|institute|"
    r"departement|verlag|press|faculty|fakultät|issn|isbn|journal|"
    r"magazine|proceedings|conference|workshop|copyright|"
    r"tag der prüfung|prüfung|berichterstatter|vorsitzender|main content)\b",
    re.I,
)

SENTENCE_RE = re.compile(
    r"\b(this|that|these|those|there|here|in britain|the oldest|"
    r"ist|sind|wird|werden|dies|diese|dieser|dieses|skip to main content)\b",
    re.I,
)

PERSON_TITLE_RE = re.compile(
    r"\b(?:prof|dr|ph\.?d|md|univ\.-?prof|dr\.-?ing|dipl\.-?ing|m\.?a|b\.?sc|m\.?sc|privatdoz)\.?\b",
    re.I,
)

PURE_NUMBER_RE = re.compile(r"^\s*[\dIVXLCMivxlcm]+\s*$")
DATEISH_RE = re.compile(
    r"^\s*(?:nr\.?\s*)?\d{1,4}(?:\s*[,./-]\s*\d{1,4}){0,3}\s*$",
    re.I,
)

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+\b", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.I)
TRAILING_PAGE_NUMBER_RE = re.compile(r"\b\d{1,4}\s*$")
HEADING_BREAK_RE = re.compile(
    r"\b(abstract|summary|contents|inhaltsverzeichnis|"
    r"references|bibliography|literatur|literaturverzeichnis)\b",
    re.I,
)

TITLE_STOP_WORDS = {
    "and", "or", "of", "the", "for", "to", "in", "on", "with",
    "und", "oder", "der", "die", "das", "des", "dem", "den",
    "et", "de", "du", "pour",
}


def _normalize(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _looks_like_title(line: str) -> bool:
    line = _normalize(line)

    if not line:
        return False
    if len(line) < 8:
        return False
    if len(line) > MAX_TITLE_LENGTH:
        return False
    if PURE_NUMBER_RE.fullmatch(line):
        return False
    if DATEISH_RE.fullmatch(line):
        return False
    if ADMIN_RE.search(line):
        return False
    if EMAIL_RE.search(line):
        return False
    if URL_RE.search(line):
        return False
    if DOI_RE.search(line):
        return False

    return True


def _clean_candidate(text: str) -> str:
    text = _normalize(text)
    text = ENUM_RE.sub("", text)
    text = PAGE_RE.sub("", text)

    parts = BY_RE.split(text)
    if len(parts) > 1:
        text = parts[0]

    text = text.strip(" ,;:-")
    return _normalize(text)


def _line_stops_title_scan(line: str) -> bool:
    line = _normalize(line)
    if not line:
        return False
    return bool(HEADING_BREAK_RE.search(line))


def _select_usable_lines(lines: list[str]) -> list[str]:
    selected: list[str] = []

    for raw_line in lines[:MAX_SCAN_LINES]:
        line = _normalize(raw_line)

        if not line:
            if selected:
                selected.append(raw_line)
            continue

        if _line_stops_title_scan(line):
            break

        selected.append(raw_line)

        non_empty_count = sum(1 for x in selected if _normalize(x))
        if non_empty_count >= MAX_CANDIDATE_LINES:
            break

    return selected


def _score_title_candidate(line_index: int, text: str) -> float:
    score = 0.0
    words = text.split()
    length = len(words)

    if 4 <= length <= 18:
        score += 3.0
    elif 3 <= length <= 25:
        score += 1.0
    else:
        score -= 1.0

    text_len = len(text)
    if 20 <= text_len <= 140:
        score += 1.0
    elif text_len > 180:
        score -= 1.0

    if UPPERCASE_RE.search(text):
        score += 1.0
    if LOWERCASE_RE.search(text):
        score += 1.0
    if ":" in text:
        score += 0.5
    if YEAR_RE.search(text):
        score += 0.2

    score += max(0, 4 - line_index)

    last = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", words[-1]).lower() if words else ""
    if last in TITLE_STOP_WORDS:
        score -= 2.0

    if PAGE_RE.search(text):
        score -= 3.0
    if ADMIN_RE.search(text):
        score -= 3.5
    if META_RE.search(text):
        score -= 4.0
    if SENTENCE_RE.search(text):
        score -= 2.0
    if EMAIL_RE.search(text):
        score -= 4.0
    if URL_RE.search(text):
        score -= 4.0
    if DOI_RE.search(text):
        score -= 4.0
    if TRAILING_PAGE_NUMBER_RE.search(text):
        score -= 3.0
    if PURE_NUMBER_RE.fullmatch(text):
        score -= 5.0
    if DATEISH_RE.fullmatch(text):
        score -= 4.0

    if PERSON_TITLE_RE.search(text):
        score -= 2.0

    comma_count = text.count(",")
    if comma_count >= 3:
        score -= 2.5
    elif comma_count == 2:
        score -= 1.5

    capitalized_words = sum(1 for w in words if w[:1].isupper())
    if 2 <= length <= 5 and capitalized_words == length and ":" not in text:
        score -= 1.5

    if text.endswith("."):
        score -= 1.0

    return score


def _score_to_confidence(score: float) -> float:
    conf = (score - 1.0) / 8.0
    if conf < 0:
        return 0.0
    if conf > 1:
        return 1.0
    return conf


def _needs_review(confidence: float, margin: float, title: str) -> bool:
    lower = title.lower()

    if confidence < 0.75:
        return True

    if margin < 1.25:
        return True

    if re.search(r"\b(by|von|par|por)\b", lower):
        return True

    if META_RE.search(lower):
        return True

    if SENTENCE_RE.search(lower):
        return True

    if EMAIL_RE.search(lower):
        return True

    if URL_RE.search(lower):
        return True

    if DOI_RE.search(lower):
        return True

    if PERSON_TITLE_RE.search(lower):
        return True

    if PURE_NUMBER_RE.fullmatch(title):
        return True

    if DATEISH_RE.fullmatch(title):
        return True

    return False


def _build_candidates(lines: list[str]) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    usable = _select_usable_lines(lines)

    for i, raw_line in enumerate(usable):
        line = _normalize(raw_line)

        if not _looks_like_title(line):
            continue

        cleaned = _clean_candidate(line)
        if not cleaned:
            continue

        candidates.append((i, cleaned))

        if i + 1 < len(usable):
            next_line = _normalize(usable[i + 1])
            if (
                next_line
                and not META_RE.search(next_line)
                and not ADMIN_RE.search(next_line)
            ):
                combined = _clean_candidate(f"{cleaned} {next_line}")
                if combined and len(combined) <= MAX_TITLE_LENGTH:
                    candidates.append((i, combined))

    seen: set[str] = set()
    unique: list[tuple[int, str]] = []

    for idx, text in candidates:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((idx, text))

    return unique


def extract_title_from_lines(lines: list[str]) -> dict[str, float | int | bool | str | list[dict[str, object]]] | None:
    candidates = _build_candidates(lines)

    if not candidates:
        return None

    scored: list[tuple[float, int, str]] = []

    for idx, text in candidates:
        score = _score_title_candidate(idx, text)
        scored.append((score, idx, text))

    scored.sort(reverse=True)

    best_score, _best_idx, best_text = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    margin = best_score - second_score
    confidence = _score_to_confidence(best_score)
    review = _needs_review(confidence, margin, best_text)

    scored_candidates = [
        {
            "score": score,
            "line_index": idx,
            "text": text,
        }
        for score, idx, text in scored
    ]

    return {
        "title": best_text,
        "score": best_score,
        "confidence": confidence,
        "margin": margin,
        "candidate_count": len(scored),
        "needs_review": review,
        "scored_candidates": scored_candidates,
    }


def _latest_source_rows(only_missing_titles: bool) -> list[tuple]:
    where_extra = "and (d.title is null or d.title = '')" if only_missing_titles else ""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    d.document_id,
                    coalesce(fm.text, tp.text, e.text_full) as source_text,
                    case
                        when fm.text is not null then 'region_front_matter_v3'
                        when tp.text is not null then 'region_title_page_v2'
                        else 'heuristic_first_lines_v4'
                    end as source_name
                from documents d
                join lateral (
                    select text_full
                    from extracted_texts
                    where document_id = d.document_id
                      and extract_status = 'ok'
                    order by created_at desc
                    limit 1
                ) e on true
                left join lateral (
                    select text
                    from document_regions
                    where document_id = d.document_id
                      and region_type = 'front_matter'
                    order by region_index asc
                    limit 1
                ) fm on true
                left join lateral (
                    select text
                    from document_regions
                    where document_id = d.document_id
                      and region_type = 'title_page'
                    order by region_index asc
                    limit 1
                ) tp on true
                where e.text_full is not null
                  and btrim(e.text_full) <> ''
                  {where_extra}
                """
            )
            return cur.fetchall()


def enrich_title_from_text() -> int:
    updated = 0
    rows = _latest_source_rows(only_missing_titles=True)

    with get_connection() as conn:
        with conn.cursor() as cur:
            for document_id, source_text, source_name in rows:
                candidates = extract_header_candidates(str(source_text))
                lines = candidates.title_lines[:40]
                result = extract_title_from_lines(lines)

                if not result:
                    continue

                kind = score_document_kind(str(source_text))
                best_kind, best_kind_score = kind.best_kind()

                review = bool(result["needs_review"])

                if best_kind in {"article_like", "magazine_article_like"} and best_kind_score >= 0.65:
                    if result["confidence"] >= 0.60 and result["margin"] >= 0.75:
                        review = False

                title_to_store = result["title"] if not review else None
                source_to_store = source_name if title_to_store else None

                cur.execute(
                    """
                    update documents
                    set title = %s,
                        title_source = %s
                    where document_id = %s
                    """,
                    (
                        title_to_store,
                        source_to_store,
                        document_id,
                    ),
                )

                if cur.rowcount:
                    updated += 1

    return updated


def rescore_existing_titles() -> int:
    updated = 0
    rows = _latest_source_rows(only_missing_titles=False)

    with get_connection() as conn:
        with conn.cursor() as cur:
            for document_id, source_text, source_name in rows:
                candidates = extract_header_candidates(str(source_text))
                lines = candidates.title_lines[:40]
                result = extract_title_from_lines(lines)

                if not result:
                    cur.execute(
                        """
                        update documents
                        set title = null,
                            title_source = null
                        where document_id = %s
                        """,
                        (document_id,),
                    )
                    updated += 1
                    continue

                kind = score_document_kind(str(source_text))
                best_kind, best_kind_score = kind.best_kind()

                review = bool(result["needs_review"])

                if best_kind in {"article_like", "magazine_article_like"} and best_kind_score >= 0.65:
                    if result["confidence"] >= 0.60 and result["margin"] >= 0.75:
                        review = False

                title_to_store = result["title"] if not review else None
                source_to_store = source_name if title_to_store else None

                cur.execute(
                    """
                    update documents
                    set title = %s,
                        title_source = %s
                    where document_id = %s
                    """,
                    (
                        title_to_store,
                        source_to_store,
                        document_id,
                    ),
                )
                updated += 1

    return updated


def enrich_titles() -> int:
    return enrich_title_from_text()
