from __future__ import annotations

import re
import uuid

from atlas.db.connection import get_connection
from atlas.lexicon.loader import score_lexicon_hits
from atlas.structure.document_kind import score_document_kind
from atlas.structure.header_candidates import extract_header_candidates

try:
    from atlas.nlp.ner import extract_person_entities
except Exception:
    def extract_person_entities(text: str) -> list[str]:
        return []

EMAIL_RE = re.compile(r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", re.I)
AUTHOR_PREFIX_LINE_RE = re.compile(r"^\s*(?:by|von|par|por|da|di|de|del|author|authors|author[s]?[:]|auteur|auteurs|autor|autores|edited by|herausgegeben von|hrsg\.?|redaktion|rédaction)\b[:\s]*", re.I)
AUTHOR_PREFIX_STRIP_RE = AUTHOR_PREFIX_LINE_RE
TITLE_FRAGMENT_RE = re.compile(r"[“”\"':]|\b(stuhl|untersuchungen|special|heritage|compendium|landscape|main content|built environment|forschungsbericht|ingenieurbüro)\b", re.I)
JOURNAL_META_RE = re.compile(r"\b(vol\.?|volume|issue|no\.?|nr\.?|pp\.?|pages?|issn|isbn|serial)\b", re.I)
SEPARATOR_RE = re.compile(r"\s*(?:,|;| and | und | et | y | & )\s*", re.I)
ROLE_WORDS_RE = re.compile(r"\b(?:editor|editors|author|authors|director|reviewer|supervisor|advisor|chair|publisher|herausgeber|hrsg|redaktion|betreuer|gutachter|erstgutachter|zweitgutachter|éditeur|éditeurs|directeur|directrice|auteur|auteurs)\b", re.I)
TITLE_WORD_RE = re.compile(r"\b(?:study|studies|analysis|report|overview|guide|manual|review|untersuchung|analyse|bericht|überblick|einführung|grundlagen|étude|rapport|guide|analyse)\b", re.I)
LOWER_CONNECTORS = {"de", "del", "der", "den", "van", "von", "zu", "zum", "zur", "la", "le", "du", "des", "da", "dos", "di", "of", "and", "und", "et", "y", "della", "delle", "dei", "del", "von"}
PERSON_TITLE_RE = re.compile(r"\b(?:prof|dr|ph\.?d|md|univ\.-?prof|dr\.-?ing|dipl\.-?ing|m\.?a|b\.?sc|m\.?sc)\.?\b", re.I)
COMMON_NON_NAME_WORDS = {"historical", "architecture", "architectural", "details", "seite", "contents", "inhaltsverzeichnis", "title", "titel", "journal", "magazine", "report", "analysis", "study", "studies", "workspace", "landesamt", "committee", "office", "guide", "special", "tag", "untersuchungen", "main", "content", "forschungsbericht", "ingenieurbüro", "fachwerkbauweisen", "heritage", "compendium", "landscape", "built"}
INSTITUTION_PATTERNS = [r"\buniversity\b", r"\buniversität\b", r"\buniversite\b", r"\buniversité\b", r"\buniversidad\b", r"\buniversita\b", r"\buniversità\b", r"\binstitute\b", r"\binstitut\b", r"\bdepartment\b", r"\bfaculty\b", r"\bfacult[eé]\b", r"\bfakult[aä]t\b", r"\bschool\b", r"\bcollege\b", r"\bpress\b", r"\bpublisher\b", r"\bjournal\b", r"\bconference\b", r"\bworkshop\b", r"\bproceedings\b", r"\bmuseum\b", r"\bsociety\b", r"\bcommission\b", r"\bcommittee\b", r"\boffice\b", r"\bresearch center\b", r"\bresearch centre\b", r"\bresearch institute\b", r"\bforschungsbereich\b", r"\bhochschule\b", r"\blehrstuhl\b", r"\bverlag\b", r"\bdépartement\b", r"\bdipartimento\b", r"\bworkspace\b", r"\blandesamt\b", r"\bmagazine\b"]


def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").strip().split())


def _is_mostly_uppercase(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.8


def _contains_common_non_name_word(text: str) -> bool:
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", text.casefold())
    return any(word in COMMON_NON_NAME_WORDS for word in words)


def _looks_like_titlecase_name_token(token: str) -> bool:
    token = token.strip("*")
    plain = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'`\-]", "", token)
    if not plain:
        return False
    if plain.casefold() in LOWER_CONNECTORS or re.fullmatch(r"[A-ZÀ-ÖØ-Ý]\.", token):
        return True
    return len(plain) == 1 or (plain[0].isupper() and not plain.isupper())


def _person_shape_score(text: str) -> float:
    value = _normalize_whitespace(text)
    words = [w for w in value.split() if w]
    if len(words) < 2 or len(words) > 4 or not any(ch.isalpha() for ch in value):
        return -10.0
    if ":" in value or any(ch.isdigit() for ch in value):
        return -8.0
    score = -3.0 if _contains_common_non_name_word(value) else 0.0
    valid_tokens = 0
    for token in words:
        if _looks_like_titlecase_name_token(token):
            valid_tokens += 1
        else:
            score -= 2.0
    if valid_tokens < 2:
        return -8.0
    score += valid_tokens * 1.2
    if _is_mostly_uppercase(value):
        score -= 2.0
    return score


def _strip_author_prefix(text: str) -> str:
    return AUTHOR_PREFIX_STRIP_RE.sub("", _normalize_whitespace(text)).strip()


def _strip_role_markers(text: str) -> str:
    value = _strip_author_prefix(text or "")
    value = PERSON_TITLE_RE.sub("", value)
    value = re.sub(r"\((.*?)\)", "", value)
    value = re.sub(r"\[(.*?)\]", "", value)
    return _normalize_whitespace(value.strip(" ,;:/-"))


def normalize_author_name(name: str) -> str:
    value = _strip_role_markers(name).casefold()
    value = re.sub(r"[^a-zà-öø-ÿ0-9'`\- ]", " ", value)
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
    return bool(value) and (any(re.search(pattern, value.lower()) for pattern in INSTITUTION_PATTERNS) or _author_penalty(value) >= 1.1)


def split_author_candidates(raw: str) -> list[str]:
    value = _strip_author_prefix(EMAIL_RE.sub("", _normalize_whitespace(raw)))
    parts = [p.strip(" ,;:/") for p in SEPARATOR_RE.split(value)]
    parts = [_strip_role_markers(p) for p in parts]
    return [p for p in parts if p]


def _is_obviously_non_person(text: str) -> bool:
    value = _normalize_whitespace(text)
    return (not value or EMAIL_RE.search(value) or _looks_like_institution(value) or _author_penalty(value) >= 0.9 or (":" in value and not AUTHOR_PREFIX_LINE_RE.match(value)) or bool(TITLE_WORD_RE.search(value)) or bool(ROLE_WORDS_RE.search(value)) or bool(JOURNAL_META_RE.search(value)) or bool(TITLE_FRAGMENT_RE.search(value)) or any(ch.isdigit() for ch in value) or len(value) > 80 or _is_mostly_uppercase(value) or _person_shape_score(value) < 1.5)


def _looks_like_person_name(text: str) -> bool:
    value = _strip_role_markers(text)
    return bool(value) and not _is_obviously_non_person(value)


def _looks_like_author_line(line: str) -> bool:
    if not line or len(line) > 120 or EMAIL_RE.search(line):
        return False
    if _author_penalty(line) >= 0.9 or JOURNAL_META_RE.search(line) or TITLE_FRAGMENT_RE.search(line):
        return False
    if ":" in line and not AUTHOR_PREFIX_LINE_RE.match(line):
        return False
    return any(_looks_like_person_name(p) for p in split_author_candidates(line))


def _split_two_twoword_names(text: str) -> list[str] | None:
    words = text.split()
    if len(words) == 4 and all(w[:1].isupper() for w in words):
        return [" ".join(words[:2]), " ".join(words[2:])]
    return None


def _split_stacked_names_fallback(text: str) -> list[str]:
    return _split_two_twoword_names(_normalize_whitespace(text)) or [_normalize_whitespace(text)]


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
            if normalized and normalized not in seen and _looks_like_person_name(cleaned) and _author_penalty(cleaned) < 0.9:
                seen.add(normalized)
                results.append(cleaned)
    return results


def _extract_header_lines_preserve_structure(text: str) -> list[str]:
    candidates = extract_header_candidates(text)
    return [_normalize_whitespace(x) for x in candidates.author_lines]


def _ner_author_candidates(text: str) -> list[str]:
    header = "\n".join(_extract_header_lines_preserve_structure(text)[:12]).strip()
    if not header:
        return []
    results: list[str] = []
    seen: set[str] = set()
    for person in extract_person_entities(header):
        cleaned = _strip_role_markers(person)
        normalized = normalize_author_name(cleaned)
        words = [w for w in cleaned.split() if w]
        if cleaned and normalized and normalized not in seen and 2 <= len(words) <= 4 and _author_penalty(cleaned) < 0.9 and not _looks_like_institution(cleaned) and ":" not in cleaned and not TITLE_FRAGMENT_RE.search(cleaned) and not JOURNAL_META_RE.search(cleaned) and _looks_like_person_name(cleaned):
            seen.add(normalized)
            results.append(cleaned)
    return results


def _heuristic_author_candidates(text: str) -> list[str]:
    header_lines = _extract_header_lines_preserve_structure(text)
    explicit = _parse_authors_from_lines([line for line in header_lines[:12] if AUTHOR_PREFIX_LINE_RE.match(line)])
    nameish = _parse_authors_from_lines([line for line in header_lines[:12] if not AUTHOR_PREFIX_LINE_RE.match(line)])
    results: list[str] = []
    seen: set[str] = set()
    for item in explicit + nameish:
        norm = normalize_author_name(item)
        if norm and norm not in seen:
            seen.add(norm)
            results.append(item)
    return results


def _upsert_author(display_name: str) -> str:
    normalized_name = normalize_author_name(display_name)
    with get_connection() as conn:
        cur = conn.cursor()
            cur.execute("select author_id from authors where normalized_name = ?", (normalized_name,))
            row = cur.fetchone()
            if row:
                return row[0]
            author_id = str(uuid.uuid4())
            cur.execute("insert into authors (author_id, display_name, normalized_name) values (?,?,?)", (author_id, display_name, normalized_name))
            return author_id


def _insert_document_author(document_id: str, author_id: str, author_position: int | None, source: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
            cur.execute("""
                insert into document_authors (document_author_id, document_id, author_id, author_position, source)
                values (?,?,?,?,?)
                on conflict (document_id, author_id) do nothing
            """, (str(uuid.uuid4()), document_id, author_id, author_position, source))
            return cur.rowcount == 1


def extract_authors_from_pdf_metadata() -> int:
    inserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
            cur.execute("select document_id, author from pdf_metadata where author is not null and btrim(author) <> ''")
            rows = cur.fetchall()
    for document_id, raw_author in rows:
        position = 1
        for candidate in split_author_candidates(raw_author):
            if _author_penalty(candidate) >= 0.9 or not _looks_like_person_name(candidate):
                continue
            author_id = _upsert_author(_strip_role_markers(candidate))
            if _insert_document_author(document_id, author_id, position, "pdf_metadata"):
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
            if normalized and normalized not in seen and _looks_like_person_name(cleaned) and _author_penalty(cleaned) < 0.9:
                seen.add(normalized)
                results.append((cleaned, position, source))
                position += 1
    return results


def extract_authors_from_text() -> int:
    inserted = 0
    with get_connection() as conn:
        cur = conn.cursor()
            cur.execute("""
                select d.document_id,
                       coalesce(fm.text, tp.text, e.text_full) as source_text
                from documents d
                join lateral (
                    select text_full from extracted_texts
                    where document_id = d.document_id and extract_status = 'ok'
                    order by created_at desc limit 1
                ) e on true
                left join lateral (
                    select text from document_regions
                    where document_id = d.document_id and region_type = 'front_matter'
                    order by region_index asc limit 1
                ) fm on true
                left join lateral (
                    select text from document_regions
                    where document_id = d.document_id and region_type = 'title_page'
                    order by region_index asc limit 1
                ) tp on true
                where e.text_full is not null and btrim(e.text_full) <> ''
            """)
            rows = cur.fetchall()
    for document_id, source_text in rows:
        for display_name, author_position, source in parse_authors_from_text(str(source_text)):
            author_id = _upsert_author(display_name)
            if _insert_document_author(document_id, author_id, author_position, source):
                inserted += 1
    return inserted


def extract_authors() -> dict[str, int]:
    metadata_count = extract_authors_from_pdf_metadata()
    text_count = extract_authors_from_text()
    return {"pdf_metadata": metadata_count, "text_heuristic": text_count, "total": metadata_count + text_count}
