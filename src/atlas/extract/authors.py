from __future__ import annotations

import re
import uuid

from atlas.db.connection import get_connection
from atlas.lexicon.loader import score_lexicon_hits
from atlas.structure.header_parse import extract_header_lines
from atlas.structure.header_candidates import extract_header_candidates
from atlas.structure.document_kind import score_document_kind

try:
    from atlas.nlp.ner import extract_person_entities
except Exception:
    def extract_person_entities(text: str) -> list[str]:
        return []


EMAIL_RE = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.I)

AUTHOR_PREFIX_LINE_RE = re.compile(
    r"^\s*(?:"
    r"by|von|par|por|da|di|de|del|"
    r"author|authors|author[s]?[:]|"
    r"auteur|auteurs|autor|autores|"
    r"edited by|herausgegeben von|hrsg\.?|"
    r"redaktion|rédaction"
    r")\b[:\s]*",
    re.I,
)

AUTHOR_PREFIX_STRIP_RE = re.compile(
    r"^\s*(?:"
    r"by|von|par|por|da|di|de|del|"
    r"author|authors|author[s]?[:]|"
    r"auteur|auteurs|autor|autores|"
    r"edited by|herausgegeben von|hrsg\.?|"
    r"redaktion|rédaction"
    r")\b[:\s]*",
    re.I,
)

TITLE_FRAGMENT_RE = re.compile(
    r"[“”\"':]|"
    r"\b(stuhl|untersuchungen|special|heritage|compendium|landscape|"
    r"main content|built environment|forschungsbericht|ingenieurbüro)\b",
    re.I,
)

JOURNAL_META_RE = re.compile(
    r"\b(vol\.?|volume|issue|no\.?|nr\.?|pp\.?|pages?|issn|isbn|serial)\b",
    re.I,
)

SEPARATOR_RE = re.compile(r"\s*(?:,|;| and | und | et | y | & )\s*", re.I)

ROLE_WORDS_RE = re.compile(
    r"\b(?:"
    r"editor|editors|author|authors|director|reviewer|supervisor|advisor|chair|publisher|"
    r"herausgeber|hrsg|redaktion|betreuer|gutachter|erstgutachter|zweitgutachter|"
    r"éditeur|éditeurs|directeur|directrice|auteur|auteurs"
    r")\b",
    re.I,
)

TITLE_WORD_RE = re.compile(
    r"\b(?:"
    r"study|studies|analysis|report|overview|guide|manual|review|"
    r"untersuchung|analyse|bericht|überblick|einführung|grundlagen|"
    r"étude|rapport|guide|analyse"
    r")\b",
    re.I,
)

LOWER_CONNECTORS = {
    "de", "del", "der", "den", "van", "von", "zu", "zum", "zur",
    "la", "le", "du", "des", "da", "dos", "di", "of", "and",
    "und", "et", "y", "della", "delle", "dei", "del", "von",
}

NAME_LINE_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+){1,3}$"
)

INITIAL_NAME_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Ý]\.\s*[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'`\-]+){0,2}$"
)

# generic institution hints, not corpus-specific
INSTITUTION_PATTERNS = [
    r"\buniversity\b",
    r"\buniversität\b",
    r"\buniversite\b",
    r"\buniversité\b",
    r"\buniversidad\b",
    r"\buniversita\b",
    r"\buniversità\b",
    r"\binstitute\b",
    r"\binstitut\b",
    r"\bdepartment\b",
    r"\bfaculty\b",
    r"\bfacult[eé]\b",
    r"\bfakult[aä]t\b",
    r"\bschool\b",
    r"\bcollege\b",
    r"\bpress\b",
    r"\bpublisher\b",
    r"\bjournal\b",
    r"\bconference\b",
    r"\bworkshop\b",
    r"\bproceedings\b",
    r"\bmuseum\b",
    r"\bsociety\b",
    r"\bcommission\b",
    r"\bcommittee\b",
    r"\boffice\b",
    r"\bresearch center\b",
    r"\bresearch centre\b",
    r"\bresearch institute\b",
    r"\bforschungsbereich\b",
    r"\bhochschule\b",
    r"\blehrstuhl\b",
    r"\bverlag\b",
    r"\bdépartement\b",
    r"\bdipartimento\b",
    r"\bworkspace\b",
    r"\blandesamt\b",
    r"\bmagazine\b",
]

PERSON_TITLE_RE = re.compile(
    r"\b(?:prof|dr|ph\.?d|md|univ\.-?prof|dr\.-?ing|dipl\.-?ing|m\.?a|b\.?sc|m\.?sc)\.?\b",
    re.I,
)

COMMON_NON_NAME_WORDS = {
    "historical", "architecture", "architectural", "details", "seite",
    "contents", "inhaltsverzeichnis", "title", "titel", "journal",
    "magazine", "report", "analysis", "study", "studies",
    "workspace", "landesamt", "committee", "office", "guide",
    "special", "tag", "untersuchungen", "main", "content",
    "forschungsbericht", "ingenieurbüro", "fachwerkbauweisen",
    "heritage", "compendium", "landscape", "built",
}


def _is_initial_token(token: str) -> bool:
    return bool(re.fullmatch(r"[A-ZÀ-ÖØ-Ý]\.", token))


def _looks_like_titlecase_name_token(token: str) -> bool:
    token = token.strip("*")
    if not token:
        return False

    if token.casefold() in LOWER_CONNECTORS:
        return True

    if _is_initial_token(token):
        return True

    plain = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'`\-]", "", token)
    if not plain:
        return False

    if len(plain) == 1:
        return plain.isalpha()

    return plain[0].isupper() and not plain.isupper()


def _contains_common_non_name_word(text: str) -> bool:
    lower = text.casefold()
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", lower)
    return any(word in COMMON_NON_NAME_WORDS for word in words)


def _person_shape_score(text: str) -> float:
    value = _normalize_whitespace(text)
    if not value:
        return -10.0

    words = [w for w in value.split() if w]
    if len(words) < 2 or len(words) > 4:
        return -10.0

    score = 0.0

    if not any(ch.isalpha() for ch in value):
        return -10.0

    if ":" in value:
        return -10.0

    if any(ch.isdigit() for ch in value):
        return -8.0

    if _contains_common_non_name_word(value):
        score -= 3.0

    valid_tokens = 0
    connector_tokens = 0

    for token in words:
        lower = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", token).casefold()

        if lower in LOWER_CONNECTORS:
            connector_tokens += 1
            continue

        if _looks_like_titlecase_name_token(token):
            valid_tokens += 1
        else:
            score -= 2.0

    if valid_tokens < 2:
        return -8.0

    score += valid_tokens * 1.2
    score -= connector_tokens * 0.2

    # penalize fully uppercase phrases
    if _is_mostly_uppercase(value):
        score -= 2.0

    return score
    
def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").strip().split())


def _strip_author_prefix(text: str) -> str:
    return AUTHOR_PREFIX_STRIP_RE.sub("", _normalize_whitespace(text)).strip()


def _strip_role_markers(text: str) -> str:
    value = _strip_author_prefix(text or "")
    value = PERSON_TITLE_RE.sub("", value)
    value = re.sub(r"\((.*?)\)", "", value)
    value = re.sub(r"\[(.*?)\]", "", value)
    value = value.strip(" ,;:/-")
    return _normalize_whitespace(value)


def _author_penalty(text: str) -> float:
    penalty, matches = score_lexicon_hits(text, scope="author")

    category_weights: dict[str, float] = {}
    for match in matches:
        category_weights[match.category] = category_weights.get(match.category, 0.0) + match.weight

    if category_weights.get("artifact", 0.0) >= 0.8:
        penalty += 1.0
    if category_weights.get("role", 0.0) >= 0.8:
        penalty += 0.7
    if category_weights.get("institution", 0.0) >= 0.8:
        penalty += 0.7
    if category_weights.get("admin", 0.0) >= 0.8:
        penalty += 0.7

    return penalty


def _looks_like_institution(text: str) -> bool:
    value = _normalize_whitespace(text)
    if not value:
        return False

    lower = value.lower()
    if any(re.search(pattern, lower) for pattern in INSTITUTION_PATTERNS):
        return True

    if _author_penalty(value) >= 1.1:
        return True

    return False


def _is_mostly_uppercase(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.8


def _token_looks_like_name_part(token: str) -> bool:
    cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'`\-]", "", token)
    if not cleaned:
        return False

    lower = cleaned.casefold()
    if lower in LOWER_CONNECTORS:
        return True

    if len(cleaned) == 1:
        return cleaned.isalpha()

    return cleaned[0].isupper()


def normalize_author_name(name: str) -> str:
    value = _strip_role_markers(name)
    value = value.casefold()
    value = re.sub(r"[^a-zà-öø-ÿ0-9'`\- ]", " ", value)
    return _normalize_whitespace(value)


def split_author_candidates(raw: str) -> list[str]:
    value = _normalize_whitespace(raw)
    if not value:
        return []

    value = EMAIL_RE.sub("", value)
    value = _strip_author_prefix(value)
    value = _normalize_whitespace(value)

    parts = [p.strip(" ,;:/") for p in SEPARATOR_RE.split(value)]
    parts = [_strip_role_markers(p) for p in parts]
    return [p for p in parts if p]

def _is_obviously_non_person(text: str) -> bool:
    value = _normalize_whitespace(text)
    if not value:
        return True

    if EMAIL_RE.search(value):
        return True
    if _looks_like_institution(value):
        return True
    if _author_penalty(value) >= 0.9:
        return True
    if ":" in value and not AUTHOR_PREFIX_LINE_RE.match(value):
        return True
    if TITLE_WORD_RE.search(value):
        return True
    if ROLE_WORDS_RE.search(value):
        return True
    if JOURNAL_META_RE.search(value):
        return True
    if TITLE_FRAGMENT_RE.search(value):
        return True
    if any(ch.isdigit() for ch in value):
        return True
    if len(value) > 80:
        return True
    if _is_mostly_uppercase(value):
        return True
    if _person_shape_score(value) < 1.5:
        return True

    return False


def _looks_like_person_name(text: str) -> bool:
    value = _strip_role_markers(text)
    if not value:
        return False

    if _is_obviously_non_person(value):
        return False

    if re.match(r"^(?:von|by|par)\s+", text or "", re.I):
        return True

    return True


def _looks_like_author_line(line: str) -> bool:
    if not line:
        return False
    if len(line) > 120:
        return False
    if _author_penalty(line) >= 0.9:
        return False
    if EMAIL_RE.search(line):
        return False
    if JOURNAL_META_RE.search(line):
        return False
    if TITLE_FRAGMENT_RE.search(line):
        return False
    if ":" in line and not AUTHOR_PREFIX_LINE_RE.match(line):
        return False

    parts = split_author_candidates(line)
    good = [p for p in parts if _looks_like_person_name(p)]
    return len(good) >= 1


def _split_stacked_names_fallback(text: str) -> list[str]:
    """
    Rescue case like:
        "Isabell Schmidt Kathleen Bugenhagen"
    when line breaks were lost.
    """
    value = _normalize_whitespace(text)
    words = value.split()

    if len(words) == 4 and all(w[:1].isupper() for w in words):
        left = " ".join(words[:2])
        right = " ".join(words[2:])
        if _looks_like_person_name(left) and _looks_like_person_name(right):
            return [left, right]

    return [value]


def _split_two_twoword_names(text: str) -> list[str] | None:
    words = text.split()
    if len(words) != 4:
        return None
    if not all(w[:1].isupper() for w in words):
        return None
    return [" ".join(words[:2]), " ".join(words[2:])]


def _parse_authors_from_lines(lines: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for line in lines:
        if not _looks_like_author_line(line) and not AUTHOR_PREFIX_LINE_RE.match(line):
            continue

        parts = split_author_candidates(line)
        if len(parts) == 1:
            parts = _split_stacked_names_fallback(parts[0])

        for part in parts:
            cleaned = _strip_role_markers(part)
            normalized = normalize_author_name(cleaned)

            if not normalized:
                continue
            if normalized in seen:
                continue
            if not _looks_like_person_name(cleaned):
                continue
            if _author_penalty(cleaned) >= 0.9:
                continue

            seen.add(normalized)
            results.append(cleaned)

    return results

def _extract_header_lines_preserve_structure(text: str) -> list[str]:
    candidates = extract_header_candidates(text)
    return [_normalize_whitespace(x) for x in candidates.author_lines]
    
def _ner_author_candidates(text: str) -> list[str]:
    header_lines = _extract_header_lines_preserve_structure(text)
    header = "\n".join(header_lines[:12]).strip()
    if not header:
        return []

    persons = extract_person_entities(header)
    results: list[str] = []
    seen: set[str] = set()

    for person in persons:
        cleaned = _strip_role_markers(person)
        normalized = _author_seen_key(cleaned)

        if not cleaned or not normalized:
            continue
        if normalized in seen:
            continue
        if _author_penalty(cleaned) >= 0.9:
            continue
        if _looks_like_institution(cleaned):
            continue
        if ":" in cleaned:
            continue
        if TITLE_FRAGMENT_RE.search(cleaned):
            continue
        if JOURNAL_META_RE.search(cleaned):
            continue

        words = [w for w in cleaned.split() if w]
        if len(words) < 2 or len(words) > 4:
            continue
        if re.fullmatch(r"[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ'\-]+\s+[A-ZÀ-ÖØ-Ý]\.", cleaned):
            continue
        if not _looks_like_person_name(cleaned):
            continue

        seen.add(normalized)
        results.append(cleaned)

    return results


def _heuristic_author_candidates(text: str) -> list[str]:
    header_lines = _extract_header_lines_preserve_structure(text)

    # explicit author lines
    explicit_lines = [line for line in header_lines[:12] if AUTHOR_PREFIX_LINE_RE.match(line)]
    explicit = _parse_authors_from_lines(explicit_lines)

    # stacked plain-name lines
    nameish_lines = []
    for line in header_lines[:12]:
        if AUTHOR_PREFIX_LINE_RE.match(line):
            continue
        if NAME_LINE_RE.match(line) or INITIAL_NAME_RE.match(line):
            nameish_lines.append(line)

    stacked = _parse_authors_from_lines(nameish_lines)

    results: list[str] = []
    seen: set[str] = set()

    for item in explicit + stacked:
        norm = normalize_author_name(item)
        if norm and norm not in seen:
            seen.add(norm)
            results.append(item)

    return results


def _upsert_author(display_name: str) -> str:
    normalized_name = normalize_author_name(display_name)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select author_id
                from authors
                where normalized_name = %s
                """,
                (normalized_name,),
            )
            row = cur.fetchone()
            if row:
                return row[0]

            author_id = str(uuid.uuid4())
            cur.execute(
                """
                insert into authors (
                    author_id,
                    display_name,
                    normalized_name
                )
                values (%s,%s,%s)
                """,
                (author_id, display_name, normalized_name),
            )
            return author_id


def _insert_document_author(
    document_id: str,
    author_id: str,
    author_position: int | None,
    source: str,
) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into document_authors (
                    document_author_id,
                    document_id,
                    author_id,
                    author_position,
                    source
                )
                values (%s,%s,%s,%s,%s)
                on conflict (document_id, author_id) do nothing
                """,
                (
                    str(uuid.uuid4()),
                    document_id,
                    author_id,
                    author_position,
                    source,
                ),
            )
            return cur.rowcount == 1


from atlas.structure.document_kind import score_document_kind


def extract_authors_from_pdf_metadata() -> int:
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    document_id,
                    author
                from pdf_metadata
                where author is not null
                  and btrim(author) <> ''
                """
            )
            rows = cur.fetchall()

    for document_id, raw_author in rows:
        position = 1
        for candidate in split_author_candidates(raw_author):
            if _author_penalty(candidate) >= 0.9:
                continue
            if not _looks_like_person_name(candidate):
                continue

            display_name = _strip_role_markers(candidate)
            normalized_name = normalize_author_name(display_name)
            if not normalized_name:
                continue

            author_id = _upsert_author(display_name)
            if _insert_document_author(
                document_id=document_id,
                author_id=author_id,
                author_position=position,
                source="pdf_metadata",
            ):
                inserted += 1
                position += 1

    return inserted

def parse_authors_from_text(text: str) -> list[tuple[str, int, str]]:
    if not text:
        return []

    results: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    position = 1

    kind = score_document_kind(text)
    best_kind, best_score = kind.best_kind()

    heuristic = _heuristic_author_candidates(text)

    sources: list[tuple[str, list[str]]] = []

    if heuristic:
        sources.append(("text_heuristic", heuristic))

        # For article-like documents, NER may add missing names.
        if best_kind in {"article_like", "magazine_article_like"} and best_score >= 0.65:
            ner_candidates = _ner_author_candidates(text)
            if ner_candidates:
                sources.append(("ner", ner_candidates))
    else:
        ner_candidates = _ner_author_candidates(text)
        if ner_candidates:
            sources.append(("ner", ner_candidates))

    for source, candidates in sources:
        for candidate in candidates:
            cleaned = _strip_role_markers(candidate)
            normalized = normalize_author_name(cleaned)

            if not normalized:
                continue
            if normalized in seen:
                continue
            if not _looks_like_person_name(cleaned):
                continue
            if _author_penalty(cleaned) >= 0.9:
                continue

            split_names = _split_two_twoword_names(cleaned)
            if split_names is not None:
                split_norms = [normalize_author_name(x) for x in split_names]
                if all(n in seen for n in split_norms):
                    continue

            seen.add(normalized)
            results.append((cleaned, position, source))
            position += 1

    return results


def extract_authors_from_text() -> int:
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    d.document_id,
                    coalesce(fm.text, tp.text, e.text_full) as source_text
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
                """
            )
            rows = cur.fetchall()

    for document_id, source_text in rows:
        candidates = parse_authors_from_text(str(source_text))

        for display_name, author_position, source in candidates:
            author_id = _upsert_author(display_name)
            if _insert_document_author(
                document_id=document_id,
                author_id=author_id,
                author_position=author_position,
                source=source,
            ):
                inserted += 1

    return inserted


def extract_authors() -> dict[str, int]:
    metadata_count = extract_authors_from_pdf_metadata()
    text_count = extract_authors_from_text()

    return {
        "pdf_metadata": metadata_count,
        "text_heuristic": text_count,
        "total": metadata_count + text_count,
    }
