from __future__ import annotations

from dataclasses import dataclass
import re


HEADER_MAX_LINES = 40

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.I)
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+\b", re.I)

BREAK_RE = re.compile(
    r"\b(abstract|summary|contents|inhaltsverzeichnis|"
    r"references|bibliography|literatur|literaturverzeichnis|"
    r"keywords?|schlagw[oö]rter|einleitung|introduction)\b",
    re.I,
)

AFFILIATION_RE = re.compile(
    r"\b(university|universit[aä]t|universite|universit[eé]|universidad|"
    r"institute|institut|department|faculty|school|college|"
    r"research center|research centre|research institute|"
    r"hochschule|lehrstuhl|verlag|museum|society|academy|"
    r"laboratory|lab|centre|center|eth zürich|eth zurich)\b",
    re.I,
)

DATE_RE = re.compile(
    r"\b("
    r"(1[5-9]\d{2}|20\d{2})|"
    r"(?:\d{1,2}[./-]\d{1,2}[./-](?:1[5-9]\d{2}|20\d{2}))|"
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|"
    r"jul|july|aug|august|sep|sept|september|oct|october|nov|november|"
    r"dec|december|m[aä]rz|mai|juni|juli|oktober|dezember)"
    r")\b",
    re.I,
)

JOURNAL_RE = re.compile(
    r"\b(journal|review|proceedings|conference|workshop|"
    r"volume|issue|band|heft|revue|issn|isbn|serial)\b",
    re.I,
)

PURE_NUMBER_RE = re.compile(r"^\s*[\dIVXLCMivxlcm]+\s*$")
PAGEISH_RE = re.compile(
    r"^\s*(?:nr\.?\s*)?\d{1,4}(?:\s*[,./-]\s*\d{1,4}){0,3}\s*$",
    re.I,
)
JOURNAL_META_RE = re.compile(
    r"\b(vol\.?|volume|issue|no\.?|nr\.?|pp\.?|pages?|issn|isbn|serial)\b",
    re.I,
)
WEB_NAV_RE = re.compile(
    r"\b(skip to main content|main content|cookie|privacy|menu|search)\b",
    re.I,
)


@dataclass(slots=True)
class HeaderLine:
    line_index: int
    text: str


@dataclass(slots=True)
class HeaderParseResult:
    lines: list[HeaderLine]
    affiliation_lines: list[HeaderLine]
    date_lines: list[HeaderLine]
    journal_lines: list[HeaderLine]


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def _is_bad_header_line(line: str) -> bool:
    if not line:
        return True

    if PURE_NUMBER_RE.fullmatch(line):
        return True

    if PAGEISH_RE.fullmatch(line):
        return True

    if WEB_NAV_RE.search(line):
        return True

    if DOI_RE.search(line) or URL_RE.search(line):
        return True

    # very metadata-like journal lines such as:
    # "Vol 51, 1995, 107-136" / "ISSN ..." / "pp. 151-166"
    if JOURNAL_META_RE.search(line):
        comma_count = line.count(",")
        digit_count = sum(ch.isdigit() for ch in line)
        if digit_count >= 4 or comma_count >= 2:
            return True

    return False


def extract_header_lines(text: str, max_lines: int = HEADER_MAX_LINES) -> list[str]:
    if not text:
        return []

    lines: list[str] = []

    for raw_line in text.splitlines():
        line = _normalize(raw_line)

        if not line:
            if lines:
                break
            continue

        if BREAK_RE.search(line):
            break

        if _is_bad_header_line(line):
            continue

        lines.append(line)

        if len(lines) >= max_lines:
            break

    return lines


def parse_header(text: str, max_lines: int = HEADER_MAX_LINES) -> HeaderParseResult:
    raw_lines = extract_header_lines(text, max_lines=max_lines)
    lines = [HeaderLine(i, line) for i, line in enumerate(raw_lines)]

    affiliation_lines: list[HeaderLine] = []
    date_lines: list[HeaderLine] = []
    journal_lines: list[HeaderLine] = []

    for item in lines:
        line = item.text

        if EMAIL_RE.search(line) or AFFILIATION_RE.search(line):
            affiliation_lines.append(item)

        if DATE_RE.search(line):
            date_lines.append(item)

        if JOURNAL_RE.search(line):
            journal_lines.append(item)

    return HeaderParseResult(
        lines=lines,
        affiliation_lines=affiliation_lines,
        date_lines=date_lines,
        journal_lines=journal_lines,
    )
