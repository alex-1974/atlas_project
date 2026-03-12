"""Generic, language-lean block features for document structure analysis.

The module intentionally stays heuristic and cheap:
- no corpus-specific assumptions
- no language model dependency
- mostly O(n) scans over short block text

Public functions from the existing API are preserved and extended with additional
signals for document understanding.
"""

from __future__ import annotations

import math
import re
from collections import Counter

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:1[6-9]\d{2}|20\d{2}|21\d{2})\b")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•‣▪◦]|\(?\d+[.)]|[A-Za-z][.)]|[IVXLCM]+[.)])\s+")
QUOTE_RE = re.compile(r"[\"'„“”«»‹›]")
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
TRAILING_PAGE_RE = re.compile(r"\b(?:\.{2,}|\s)\s*(\d{1,4})\s*$")
ENUMERATION_RE = re.compile(r"^\s*(?:\d+(?:\.\d+){0,4}|[A-Z]|[IVXLCM]{1,8})[.)]?\s+")
WORD_RE = re.compile(r"\b[\wÀ-ÿ-]+\b", re.UNICODE)
MONTH_NAME_RE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan(?:uar)?|feb(?:ruar)?|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)\b",
    re.IGNORECASE,
)
FULL_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[./-]\d{1,2}[./-](?:\d{2}|\d{4})|(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan(?:uar)?|Feb(?:ruar)?|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+\d{2,4})\b",
    re.IGNORECASE,
)
ABSTRACT_MARKER_RE = re.compile(r"^\s*(?:abstract|summary|zusammenfassung|résumé|resumé)\s*:?\s*$", re.IGNORECASE)
KEYWORDS_MARKER_RE = re.compile(r"^\s*(?:keywords|key words|schlagw(?:ö|o)rter|mots[- ]clés)\s*:?\s*$", re.IGNORECASE)
CONTENTS_MARKER_RE = re.compile(r"^\s*(?:contents|table of contents|inhalt|inhaltsverzeichnis|sommaire)\s*:?\s*$", re.IGNORECASE)
REFERENCES_MARKER_RE = re.compile(r"^\s*(?:references|bibliography|works cited|literatur|literaturverzeichnis|bibliographie|quellen)\s*:?\s*$", re.IGNORECASE)
AFFILIATION_KEYWORD_RE = re.compile(
    r"\b(?:university|universität|department|institute|institut|faculty|school|hospital|clinic|klinikum|"
    r"centre|center|laboratory|lab|chair|division)\b",
    re.IGNORECASE,
)
CAPTION_MARKER_RE = re.compile(r"^\s*(?:figure|fig\.?|table|tab\.?|abb\.?|abbildung)\s*\d+", re.IGNORECASE)
FOOTNOTE_MARKER_RE = re.compile(r"(?:^\s*\d+[.)]\s+|\[\d+\]|\(\d+\))")
PARENTHETICAL_CITATION_RE = re.compile(
    r"\(([A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+(?:,?\s+(?:and|&|und)\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+)?(?:\s+et\s+al\.)?"
    r"(?:,\s*)?\s*(?:18|19|20)\d{2}[a-z]?(?:;\s*[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+(?:,\s*)?\s*(?:18|19|20)\d{2}[a-z]?)*\))"
)
AUTHOR_INITIAL_PATTERN_RE = re.compile(r"\b[A-ZÄÖÜ][a-zäöüß]+,\s*[A-Z](?:\.[A-Z])*\.?\b", re.UNICODE)
AUTHOR_NAME_LINE_RE = re.compile(
    r"^\s*(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+){1,3}"
    r"(?:\s*,\s*[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'`-]+){1,3})*)\s*$"
)
LEADER_DOT_RE = re.compile(r"\.{3,}")
LINE_END_DIGIT_RE = re.compile(r"\d{1,4}\s*$")
INITIAL_ENUMERATION_LINE_RE = re.compile(r"^\s*(?:\d+(?:\.\d+){0,4}|[A-Z]|[IVXLCM]{1,8})[.)]?\s+")

SECTION_KEYWORDS = {
    "abstract",
    "summary",
    "keywords",
    "introduction",
    "einleitung",
    "references",
    "bibliography",
    "literatur",
    "literaturverzeichnis",
    "contents",
    "inhalt",
    "appendix",
    "conclusion",
    "discussion",
}

NEGATIVE_TITLE_TERMS = {
    "figure",
    "table",
    "editor",
    "department",
    "volume",
    "issue",
    "copyright",
    "license",
}


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def _nonempty_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def char_count(text: str) -> int:
    return len(text or "")


def word_count(text: str) -> int:
    return len(_words(text))


def line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def avg_line_length(text: str) -> float:
    lines = _nonempty_lines(text)
    if not lines:
        return 0.0
    return sum(len(ln) for ln in lines) / len(lines)


def digit_ratio(text: str) -> float:
    text = text or ""
    return _safe_div(sum(ch.isdigit() for ch in text), len(text))


def uppercase_ratio(text: str) -> float:
    letters = [ch for ch in (text or "") if ch.isalpha()]
    return _safe_div(sum(ch.isupper() for ch in letters), len(letters))


def lowercase_ratio(text: str) -> float:
    letters = [ch for ch in (text or "") if ch.isalpha()]
    return _safe_div(sum(ch.islower() for ch in letters), len(letters))


def whitespace_ratio(text: str) -> float:
    text = text or ""
    return _safe_div(sum(ch.isspace() for ch in text), len(text))


def punctuation_ratio(text: str) -> float:
    text = text or ""
    return _safe_div(sum(not ch.isalnum() and not ch.isspace() for ch in text), len(text))


def comma_density(text: str) -> float:
    return _safe_div((text or "").count(","), max(1, word_count(text)))


def period_density(text: str) -> float:
    return _safe_div((text or "").count("."), max(1, word_count(text)))


def colon_density(text: str) -> float:
    return _safe_div((text or "").count(":"), max(1, word_count(text)))


def semicolon_density(text: str) -> float:
    return _safe_div((text or "").count(";"), max(1, word_count(text)))


def year_density(text: str) -> float:
    years = YEAR_RE.findall(text or "")
    return _safe_div(len(years), max(1, word_count(text)))


def long_word_ratio(text: str, threshold: int = 8) -> float:
    words = _words(text)
    return _safe_div(sum(len(w) >= threshold for w in words), len(words))


def titlecase_ratio(text: str) -> float:
    words = [w for w in _words(text) if any(ch.isalpha() for ch in w)]
    return _safe_div(sum(w[:1].isupper() and w[1:].islower() for w in words if len(w) > 1), len(words))


def repeated_token_ratio(text: str) -> float:
    words = [w.lower() for w in _words(text)]
    if not words:
        return 0.0
    counts = Counter(words)
    repeated = sum(c for c in counts.values() if c > 1)
    return _safe_div(repeated, len(words))


def lexical_diversity(text: str) -> float:
    words = [w.lower() for w in _words(text)]
    return _safe_div(len(set(words)), len(words))


def has_terminal_period(text: str) -> bool:
    return (text or "").rstrip().endswith(".")


def has_terminal_question(text: str) -> bool:
    return (text or "").rstrip().endswith("?")


def has_terminal_exclamation(text: str) -> bool:
    return (text or "").rstrip().endswith("!")


def starts_with_list_marker(text: str) -> bool:
    return bool(LIST_MARKER_RE.search(text or ""))


def starts_with_enumeration(text: str) -> bool:
    return bool(ENUMERATION_RE.search(text or ""))


def contains_year(text: str) -> bool:
    return bool(YEAR_RE.search(text or ""))


def contains_doi(text: str) -> bool:
    return bool(DOI_RE.search(text or ""))


def contains_url(text: str) -> bool:
    return bool(URL_RE.search(text or ""))


def contains_email(text: str) -> bool:
    return bool(EMAIL_RE.search(text or ""))


def contains_quotes(text: str) -> bool:
    return bool(QUOTE_RE.search(text or ""))


def page_number_only(text: str) -> bool:
    return bool(PAGE_NUMBER_RE.fullmatch(text or ""))


def trailing_page_number(text: str) -> bool:
    return bool(TRAILING_PAGE_RE.search(text or ""))


def line_length_stdev(text: str) -> float:
    lines = [len(ln.rstrip()) for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return 0.0
    mean = sum(lines) / len(lines)
    return math.sqrt(sum((x - mean) ** 2 for x in lines) / len(lines))


def first_line_word_count(text: str) -> int:
    first = (text or "").splitlines()[0] if text else ""
    return word_count(first)


def last_line_word_count(text: str) -> int:
    last = (text or "").splitlines()[-1] if text else ""
    return word_count(last)


def section_keyword_score(text: str) -> float:
    words = {w.lower() for w in _words(text)}
    if not words:
        return 0.0
    hits = len(words & SECTION_KEYWORDS)
    return min(1.0, hits / 2.0)


def negative_title_term_score(text: str) -> float:
    words = {w.lower() for w in _words(text)}
    hits = len(words & NEGATIVE_TITLE_TERMS)
    return min(1.0, hits / 2.0)


def looks_sentence_like(text: str) -> bool:
    words = word_count(text)
    return words >= 8 and has_terminal_period(text)


def contains_month_name(text: str) -> bool:
    return bool(MONTH_NAME_RE.search(text or ""))


def contains_full_date(text: str) -> bool:
    return bool(FULL_DATE_RE.search(text or ""))


def contains_abstract_marker(text: str) -> bool:
    return bool(ABSTRACT_MARKER_RE.match((text or "").strip()))


def contains_keywords_marker(text: str) -> bool:
    return bool(KEYWORDS_MARKER_RE.match((text or "").strip()))


def contains_contents_marker(text: str) -> bool:
    return bool(CONTENTS_MARKER_RE.match((text or "").strip()))


def contains_references_marker(text: str) -> bool:
    return bool(REFERENCES_MARKER_RE.match((text or "").strip()))


def contains_affiliation_keyword(text: str) -> bool:
    return bool(AFFILIATION_KEYWORD_RE.search(text or ""))


def contains_caption_marker(text: str) -> bool:
    return bool(CAPTION_MARKER_RE.match((text or "").strip()))


def contains_footnote_marker(text: str) -> bool:
    return bool(FOOTNOTE_MARKER_RE.search(text or ""))


def contains_parenthetical_citation(text: str) -> bool:
    return bool(PARENTHETICAL_CITATION_RE.search(text or ""))


def parenthetical_citation_count(text: str) -> int:
    return len(PARENTHETICAL_CITATION_RE.findall(text or ""))


def leader_dot_ratio(text: str) -> float:
    lines = _nonempty_lines(text)
    if not lines:
        return 0.0
    hits = sum(1 for ln in lines if LEADER_DOT_RE.search(ln))
    return _safe_div(hits, len(lines))


def line_end_digit_ratio(text: str) -> float:
    lines = _nonempty_lines(text)
    if not lines:
        return 0.0
    hits = sum(1 for ln in lines if LINE_END_DIGIT_RE.search(ln))
    return _safe_div(hits, len(lines))


def short_line_ratio(text: str, threshold: int = 80) -> float:
    lines = _nonempty_lines(text)
    if not lines:
        return 0.0
    hits = sum(1 for ln in lines if len(ln) <= threshold)
    return _safe_div(hits, len(lines))


def line_initial_enumeration_ratio(text: str) -> float:
    lines = _nonempty_lines(text)
    if not lines:
        return 0.0
    hits = sum(1 for ln in lines if INITIAL_ENUMERATION_LINE_RE.search(ln))
    return _safe_div(hits, len(lines))


def author_initial_pattern_count(text: str) -> int:
    return len(AUTHOR_INITIAL_PATTERN_RE.findall(text or ""))


def author_name_line_count(text: str) -> int:
    lines = _nonempty_lines(text)
    return sum(1 for ln in lines if AUTHOR_NAME_LINE_RE.match(ln))


def collect_block_features(text: str) -> dict[str, float | bool | int]:
    """Return a compact generic feature vector for a block.

    Optimized hot-path version:
    - one line split
    - one word extraction
    - one character scan
    - reuse intermediate values instead of recomputing them in helpers
    """
    text = text or ""

    # Basic splits
    lines = text.splitlines()
    nonempty_lines = [ln.strip() for ln in lines if ln.strip()]
    words = WORD_RE.findall(text)
    lower_words = [w.lower() for w in words]
    word_count_value = len(words)
    char_count_value = len(text)
    line_count_value = len(lines)

    # Single character scan
    digits = 0
    uppercase = 0
    lowercase = 0
    whitespace = 0
    punctuation = 0
    letters = 0

    for ch in text:
        if ch.isdigit():
            digits += 1
        elif ch.isalpha():
            letters += 1
            if ch.isupper():
                uppercase += 1
            else:
                lowercase += 1
        elif ch.isspace():
            whitespace += 1
        else:
            punctuation += 1

    digit_ratio_value = _safe_div(digits, char_count_value)
    uppercase_ratio_value = _safe_div(uppercase, letters)
    lowercase_ratio_value = _safe_div(lowercase, letters)
    whitespace_ratio_value = _safe_div(whitespace, char_count_value)
    punctuation_ratio_value = _safe_div(punctuation, char_count_value)

    # Line stats
    if nonempty_lines:
        avg_line_length_value = sum(len(ln) for ln in nonempty_lines) / len(nonempty_lines)

        line_lengths = [len(ln.rstrip()) for ln in lines if ln.strip()]
        if len(line_lengths) >= 2:
            mean = sum(line_lengths) / len(line_lengths)
            line_length_stdev_value = math.sqrt(
                sum((x - mean) ** 2 for x in line_lengths) / len(line_lengths)
            )
        else:
            line_length_stdev_value = 0.0

        leader_dot_ratio_value = _safe_div(
            sum(1 for ln in nonempty_lines if LEADER_DOT_RE.search(ln)),
            len(nonempty_lines),
        )
        line_end_digit_ratio_value = _safe_div(
            sum(1 for ln in nonempty_lines if LINE_END_DIGIT_RE.search(ln)),
            len(nonempty_lines),
        )
        short_line_ratio_value = _safe_div(
            sum(1 for ln in nonempty_lines if len(ln) <= 80),
            len(nonempty_lines),
        )
        line_initial_enumeration_ratio_value = _safe_div(
            sum(1 for ln in nonempty_lines if INITIAL_ENUMERATION_LINE_RE.search(ln)),
            len(nonempty_lines),
        )
        author_name_line_count_value = sum(
            1 for ln in nonempty_lines if AUTHOR_NAME_LINE_RE.match(ln)
        )
    else:
        avg_line_length_value = 0.0
        line_length_stdev_value = 0.0
        leader_dot_ratio_value = 0.0
        line_end_digit_ratio_value = 0.0
        short_line_ratio_value = 0.0
        line_initial_enumeration_ratio_value = 0.0
        author_name_line_count_value = 0

    # Word stats
    if words:
        long_word_ratio_value = _safe_div(sum(len(w) >= 8 for w in words), len(words))
        titlecase_ratio_value = _safe_div(
            sum(w[:1].isupper() and w[1:].islower() for w in words if len(w) > 1),
            len(words),
        )
        counts = Counter(lower_words)
        repeated = sum(c for c in counts.values() if c > 1)
        repeated_token_ratio_value = _safe_div(repeated, len(words))
        lexical_diversity_value = _safe_div(len(set(lower_words)), len(words))
        word_set = set(lower_words)
    else:
        long_word_ratio_value = 0.0
        titlecase_ratio_value = 0.0
        repeated_token_ratio_value = 0.0
        lexical_diversity_value = 0.0
        word_set = set()

    # Cheap scalar counts
    comma_density_value = _safe_div(text.count(","), max(1, word_count_value))
    period_density_value = _safe_div(text.count("."), max(1, word_count_value))
    colon_density_value = _safe_div(text.count(":"), max(1, word_count_value))
    semicolon_density_value = _safe_div(text.count(";"), max(1, word_count_value))
    year_matches = YEAR_RE.findall(text)
    year_density_value = _safe_div(len(year_matches), max(1, word_count_value))

    # Simple regex detections
    contains_year_value = bool(year_matches)
    contains_doi_value = bool(DOI_RE.search(text))
    contains_url_value = bool(URL_RE.search(text))
    contains_email_value = bool(EMAIL_RE.search(text))
    contains_quotes_value = bool(QUOTE_RE.search(text))
    page_number_only_value = bool(PAGE_NUMBER_RE.fullmatch(text))
    trailing_page_number_value = bool(TRAILING_PAGE_RE.search(text))
    contains_month_name_value = bool(MONTH_NAME_RE.search(text))
    contains_full_date_value = bool(FULL_DATE_RE.search(text))
    contains_abstract_marker_value = bool(ABSTRACT_MARKER_RE.match(text.strip()))
    contains_keywords_marker_value = bool(KEYWORDS_MARKER_RE.match(text.strip()))
    contains_contents_marker_value = bool(CONTENTS_MARKER_RE.match(text.strip()))
    contains_references_marker_value = bool(REFERENCES_MARKER_RE.match(text.strip()))
    contains_affiliation_keyword_value = bool(AFFILIATION_KEYWORD_RE.search(text))
    contains_caption_marker_value = bool(CAPTION_MARKER_RE.match(text.strip()))
    contains_footnote_marker_value = bool(FOOTNOTE_MARKER_RE.search(text))
    contains_parenthetical_citation_value = bool(PARENTHETICAL_CITATION_RE.search(text))
    parenthetical_citation_count_value = len(PARENTHETICAL_CITATION_RE.findall(text))
    author_initial_pattern_count_value = len(AUTHOR_INITIAL_PATTERN_RE.findall(text))

    # Structural booleans
    stripped = text.rstrip()
    has_terminal_period_value = stripped.endswith(".")
    has_terminal_question_value = stripped.endswith("?")
    has_terminal_exclamation_value = stripped.endswith("!")
    starts_with_list_marker_value = bool(LIST_MARKER_RE.search(text))
    starts_with_enumeration_value = bool(ENUMERATION_RE.search(text))
    looks_sentence_like_value = word_count_value >= 8 and has_terminal_period_value

    # Keyword scores
    section_keyword_score_value = min(1.0, len(word_set & SECTION_KEYWORDS) / 2.0) if word_set else 0.0
    negative_title_term_score_value = min(1.0, len(word_set & NEGATIVE_TITLE_TERMS) / 2.0) if word_set else 0.0

    # First / last line word counts
    first_line = lines[0] if lines else ""
    last_line = lines[-1] if lines else ""
    first_line_word_count_value = len(WORD_RE.findall(first_line))
    last_line_word_count_value = len(WORD_RE.findall(last_line))

    return {
        "char_count": char_count_value,
        "word_count": word_count_value,
        "line_count": line_count_value,
        "avg_line_length": round(avg_line_length_value, 4),
        "line_length_stdev": round(line_length_stdev_value, 4),
        "first_line_word_count": first_line_word_count_value,
        "last_line_word_count": last_line_word_count_value,
        "digit_ratio": round(digit_ratio_value, 4),
        "uppercase_ratio": round(uppercase_ratio_value, 4),
        "lowercase_ratio": round(lowercase_ratio_value, 4),
        "whitespace_ratio": round(whitespace_ratio_value, 4),
        "punctuation_ratio": round(punctuation_ratio_value, 4),
        "comma_density": round(comma_density_value, 4),
        "period_density": round(period_density_value, 4),
        "colon_density": round(colon_density_value, 4),
        "semicolon_density": round(semicolon_density_value, 4),
        "year_density": round(year_density_value, 4),
        "long_word_ratio": round(long_word_ratio_value, 4),
        "titlecase_ratio": round(titlecase_ratio_value, 4),
        "repeated_token_ratio": round(repeated_token_ratio_value, 4),
        "lexical_diversity": round(lexical_diversity_value, 4),
        "has_terminal_period": has_terminal_period_value,
        "has_terminal_question": has_terminal_question_value,
        "has_terminal_exclamation": has_terminal_exclamation_value,
        "starts_with_list_marker": starts_with_list_marker_value,
        "starts_with_enumeration": starts_with_enumeration_value,
        "contains_year": contains_year_value,
        "contains_doi": contains_doi_value,
        "contains_url": contains_url_value,
        "contains_email": contains_email_value,
        "contains_quotes": contains_quotes_value,
        "page_number_only": page_number_only_value,
        "trailing_page_number": trailing_page_number_value,
        "section_keyword_score": round(section_keyword_score_value, 4),
        "negative_title_term_score": round(negative_title_term_score_value, 4),
        "looks_sentence_like": looks_sentence_like_value,
        "contains_month_name": contains_month_name_value,
        "contains_full_date": contains_full_date_value,
        "contains_abstract_marker": contains_abstract_marker_value,
        "contains_keywords_marker": contains_keywords_marker_value,
        "contains_contents_marker": contains_contents_marker_value,
        "contains_references_marker": contains_references_marker_value,
        "contains_affiliation_keyword": contains_affiliation_keyword_value,
        "contains_caption_marker": contains_caption_marker_value,
        "contains_footnote_marker": contains_footnote_marker_value,
        "contains_parenthetical_citation": contains_parenthetical_citation_value,
        "parenthetical_citation_count": parenthetical_citation_count_value,
        "leader_dot_ratio": round(leader_dot_ratio_value, 4),
        "line_end_digit_ratio": round(line_end_digit_ratio_value, 4),
        "short_line_ratio": round(short_line_ratio_value, 4),
        "line_initial_enumeration_ratio": round(line_initial_enumeration_ratio_value, 4),
        "author_initial_pattern_count": author_initial_pattern_count_value,
        "author_name_line_count": author_name_line_count_value,
    }
