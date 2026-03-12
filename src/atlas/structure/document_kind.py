from __future__ import annotations

from dataclasses import dataclass
import re

from atlas.structure.header_parse import parse_header


ISSUE_YEAR_PAGE_RE = re.compile(
    r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\- ]{2,}\s+\d{1,2}\s*/\s*(?:19|20)\d{2}\s+\d{1,4}\b"
)
ISSUE_YEAR_RE = re.compile(
    r"\b(?:heft|nr\.?|no\.?|issue|band|vol\.?|volume)?\s*\d{1,2}\s*/\s*(?:19|20)\d{2}\b",
    re.I,
)
THESIS_RE = re.compile(
    r"\b(dissertation|thesis|diplomarbeit|masterarbeit|bachelorarbeit|"
    r"zur erlangung|vorgelegt|submitted|eingereicht)\b",
    re.I,
)
REPORT_RE = re.compile(
    r"\b(report|bericht|guidance|leitfaden|handreichung|manual|forschungsbericht)\b",
    re.I,
)
TEACHING_RE = re.compile(
    r"\b(vorlesung|lecture|seminar|skript|script|reader|course|kurs)\b",
    re.I,
)
BOOK_CHAPTER_RE = re.compile(
    r"\b(kapitel|chapter|teil\s+\d+|part\s+\d+)\b",
    re.I,
)
TOC_RE = re.compile(
    r"\b(contents|table of contents|inhalt|inhaltsverzeichnis|sommaire)\b",
    re.I,
)
ABSTRACT_RE = re.compile(
    r"^\s*(abstract|summary|zusammenfassung|résumé|resumé)\s*:?\s*$",
    re.I,
)
REFERENCES_RE = re.compile(
    r"^\s*(references|bibliography|works cited|literatur|literaturverzeichnis|bibliographie)\s*:?\s*$",
    re.I,
)
AUTHOR_PREFIX_RE = re.compile(r"^\s*(by|von|par|por)\b", re.I)
ROLE_RE = re.compile(
    r"\b(betreuer|gutachter|berichterstatter|vorsitzender|supervisor|advisor|chair)\b",
    re.I,
)
PERSON_TITLE_RE = re.compile(
    r"\b(?:prof|dr|ph\.?d|md|univ\.-?prof|dr\.-?ing|dipl\.-?ing|m\.?a|m\.?sc|b\.?sc|privatdoz)\.?\b",
    re.I,
)


@dataclass(slots=True)
class DocumentKindScores:
    article_like: float
    magazine_article_like: float
    thesis_like: float
    report_like: float
    teaching_material_like: float
    book_chapter_like: float
    toc_document_like: float

    def best_kind(self) -> tuple[str, float]:
        pairs = [
            ("article_like", self.article_like),
            ("magazine_article_like", self.magazine_article_like),
            ("thesis_like", self.thesis_like),
            ("report_like", self.report_like),
            ("teaching_material_like", self.teaching_material_like),
            ("book_chapter_like", self.book_chapter_like),
            ("toc_document_like", self.toc_document_like),
        ]
        return max(pairs, key=lambda x: x[1])


def _clip(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return round(value, 4)


def _norm(text: str) -> str:
    return " ".join((text or "").strip().split())


def _early_nonempty_lines(text: str, limit: int = 24) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = _norm(raw)
        if not line:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _looks_like_author_line(line: str) -> bool:
    if not line:
        return False
    if AUTHOR_PREFIX_RE.search(line):
        return True
    words = line.split()
    if not (2 <= len(words) <= 6):
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if ROLE_RE.search(line):
        return False
    capitals = sum(1 for w in words if w[:1].isupper())
    if capitals >= 2:
        return True
    return False


def score_document_kind(text: str) -> DocumentKindScores:
    parsed = parse_header(text or "", max_lines=40)
    early_lines = _early_nonempty_lines(text or "", limit=24)

    header_lines = [x.text for x in parsed.lines]
    header_text = "\n".join(header_lines[:12])
    early_text = "\n".join(early_lines)

    line_count = len(early_lines)
    author_like_lines = sum(1 for line in header_lines[:8] if _looks_like_author_line(line))
    affiliation_count = len(parsed.affiliation_lines)
    journal_count = len(parsed.journal_lines)
    date_count = len(parsed.date_lines)

    has_abstract = any(ABSTRACT_RE.match(line) for line in early_lines[:12])
    has_references_marker = any(REFERENCES_RE.match(line) for line in early_lines)
    has_toc_marker = any(TOC_RE.search(line) for line in early_lines[:12])

    issue_year_page = bool(ISSUE_YEAR_PAGE_RE.search(early_text))
    issue_year = bool(ISSUE_YEAR_RE.search(early_text))
    thesis_marker = bool(THESIS_RE.search(early_text))
    report_marker = bool(REPORT_RE.search(early_text))
    teaching_marker = bool(TEACHING_RE.search(early_text))
    chapter_marker = bool(BOOK_CHAPTER_RE.search(early_text))
    role_marker = bool(ROLE_RE.search(early_text))

    body_starts_early = False
    if len(early_lines) >= 4:
        tail = early_lines[min(3, len(early_lines) - 1)]
        body_starts_early = len(tail.split()) >= 8

    toc_density = 0.0
    if early_lines:
        tocish = 0
        for line in early_lines[:12]:
            if re.search(r"\.{3,}\s*\d{1,4}\s*$", line):
                tocish += 1
            elif re.search(r"\d{1,4}\s*$", line) and len(line.split()) <= 10:
                tocish += 1
        toc_density = tocish / min(len(early_lines), 12)

    article = 0.0
    article += 0.22 if author_like_lines >= 1 else 0.0
    article += 0.18 if journal_count >= 1 else 0.0
    article += 0.12 if date_count >= 1 else 0.0
    article += 0.14 if has_abstract else 0.0
    article += 0.12 if has_references_marker else 0.0
    article += 0.12 if body_starts_early else 0.0
    article -= 0.28 if thesis_marker else 0.0
    article -= 0.18 if has_toc_marker or toc_density >= 0.4 else 0.0
    article -= 0.12 if role_marker else 0.0

    magazine = 0.0
    magazine += 0.38 if issue_year_page else 0.0
    magazine += 0.22 if issue_year else 0.0
    magazine += 0.16 if author_like_lines >= 1 else 0.0
    magazine += 0.14 if body_starts_early else 0.0
    magazine += 0.08 if journal_count >= 1 else 0.0
    magazine -= 0.22 if thesis_marker else 0.0
    magazine -= 0.18 if has_toc_marker or toc_density >= 0.4 else 0.0
    magazine -= 0.10 if affiliation_count >= 2 and has_abstract else 0.0

    thesis = 0.0
    thesis += 0.42 if thesis_marker else 0.0
    thesis += 0.18 if role_marker else 0.0
    thesis += 0.16 if affiliation_count >= 1 else 0.0
    thesis += 0.08 if date_count >= 1 else 0.0
    thesis += 0.10 if has_toc_marker else 0.0
    thesis -= 0.24 if issue_year_page else 0.0
    thesis -= 0.18 if body_starts_early else 0.0

    report = 0.0
    report += 0.30 if report_marker else 0.0
    report += 0.14 if affiliation_count >= 1 else 0.0
    report += 0.12 if date_count >= 1 else 0.0
    report += 0.10 if author_like_lines <= 1 else 0.0
    report += 0.10 if not has_abstract else 0.0
    report -= 0.20 if thesis_marker else 0.0
    report -= 0.16 if issue_year_page else 0.0

    teaching = 0.0
    teaching += 0.34 if teaching_marker else 0.0
    teaching += 0.16 if affiliation_count >= 1 else 0.0
    teaching += 0.12 if author_like_lines >= 1 else 0.0
    teaching += 0.08 if not has_references_marker else 0.0
    teaching -= 0.20 if issue_year_page else 0.0
    teaching -= 0.18 if thesis_marker else 0.0

    chapter = 0.0
    chapter += 0.26 if chapter_marker else 0.0
    chapter += 0.14 if author_like_lines >= 1 else 0.0
    chapter += 0.10 if body_starts_early else 0.0
    chapter += 0.10 if has_references_marker else 0.0
    chapter -= 0.16 if issue_year_page else 0.0
    chapter -= 0.18 if thesis_marker else 0.0

    toc_doc = 0.0
    toc_doc += 0.42 if has_toc_marker else 0.0
    toc_doc += 0.28 if toc_density >= 0.4 else 0.0
    toc_doc += 0.10 if line_count >= 6 and not body_starts_early else 0.0
    toc_doc -= 0.24 if author_like_lines >= 1 else 0.0
    toc_doc -= 0.20 if issue_year_page else 0.0

    return DocumentKindScores(
        article_like=_clip(article),
        magazine_article_like=_clip(magazine),
        thesis_like=_clip(thesis),
        report_like=_clip(report),
        teaching_material_like=_clip(teaching),
        book_chapter_like=_clip(chapter),
        toc_document_like=_clip(toc_doc),
    )
