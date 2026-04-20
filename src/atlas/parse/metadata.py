"""
atlas.parse.metadata

Extrahiert bibliografische Kernmetadaten aus dem Frontmatter-Bereich.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf as fitz

from .logging import get_logger
from .document_type_hints import infer_document_type_hint
from .section_labels import ABSTRACT_RE

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Identifier-Patterns
# ---------------------------------------------------------------------------

_DOI_RE  = re.compile(r"\b(10\.\d{4,}/\S+?)(?:[.,;)\s]|$)", re.IGNORECASE)
_ISBN_RE = re.compile(r"ISBN[\s:\-]*([\d\-]{10,17}[\dX])", re.IGNORECASE)
_ISSN_RE = re.compile(r"ISSN[\s:\-]*(\d{4}-\d{3}[\dX])", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")

_AUTHOR_PREFIX_RE = re.compile(
    r"^\s*(?:by|von|par|di|door|por|autor(?:en)?|"
    r"herausgegeben\s+von|edited\s+by|hrsg\.?\s+v(?:on)?\.?)\s+",
    re.IGNORECASE,
)
_NAME_ABBREV_RE = re.compile(
    r"\b(?:dr\.?|prof\.?|m\.a\.?|b\.a\.?|ph\.d\.?|igb|dipl\.?-?(?:ing\.?)?)\b",
    re.IGNORECASE,
)
_INSTITUTION_WORDS_RE = re.compile(
    r"\b(?:university|institut(?:e)?|verlag|publisher|press|wiley|springer|"
    r"society|association|club|committee|foundation|trust|council|authority|"
    r"agency|edition|auflage|volume|band|series|reihe|guide|essay|"
    r"revised|updated|sixth|fifth|fourth|third|second|first|"
    r"sechste|f\u00fcnfte|dritte|zweite|stimmen|overview|introduction|"
    r"impressum|imprint|contents|inhalt|collection|summary|zusammenfassung|"
    r"informing|managing|dereliction|collapse|redundancy|maintenance|repair)\b",
    re.IGNORECASE,
)
_AND_RE = re.compile(r"\b(?:and|und)\b", re.IGNORECASE)
_PERSONAL_NAME_RE = re.compile(
    r"(?:[A-Z\u00c4\u00d6\u00dc]\.\s*){1,3}[A-Z\u00c4\u00d6\u00dc][a-z\u00e4\u00f6\u00fc\u00df]+"
    r"|[A-Z\u00c4\u00d6\u00dc][a-z\u00e4\u00f6\u00fc\u00df]{2,}\s+[A-Z\u00c4\u00d6\u00dc][a-z\u00e4\u00f6\u00fc\u00df]+"
    r"|[A-Z\u00c4\u00d6\u00dc][a-z\u00e4\u00f6\u00fc\u00df]{2,}",
)


_NOT_TITLE_RE = re.compile(
    r"^\s*(?:"
    r"\d+\s*$"
    r"|\w+\s+\d+\s*$"
    r"|fig\.?\s*\d|abb\.?\s*\d"
    r"|table\s+\d|tabelle\s+\d"
    r"|copyright\s*\xa9|all\s+rights\s+reserved|printed\s+in"
    r"|isbn|issn|doi"
    r"|(?:summary|contents|introduction|abstract|impressum|zusammenfassung|inhaltsverzeichnis|inhalt)\s*$"
    r")",
    re.IGNORECASE,
)

_TOC_ENTRY_RE = re.compile(r"\.{3,}\s*\d+\s*$|\s{3,}\d+\s*$")



# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExtractedMetadata:
    title: str | None = None
    title_confidence: float = 0.0
    title_page: int | None = None
    authors: list[str] = field(default_factory=list)
    authors_confidence: float = 0.0
    year: int | None = None
    doi: str | None = None
    isbn: str | None = None
    issn: str | None = None
    abstract: str | None = None
    abstract_confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _span_text(span: dict) -> str:
    t = span.get("text", "")
    if t:
        return t
    return "".join(c.get("c", "") for c in span.get("chars", []))


def _block_text(block: dict) -> str:
    parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = _span_text(span).strip()
            if t:
                parts.append(t)
    return " ".join(parts)


def _block_first_line(block: dict) -> str:
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = _span_text(span).strip()
            if t:
                return t
    return ""


def _dominant_size(block: dict) -> float:
    sizes = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = _span_text(span).strip()
            if t:
                s = float(span.get("size", 0.0))
                if s > 0:
                    sizes.append(s)
    if not sizes:
        return 0.0
    sizes.sort()
    mid = len(sizes) // 2
    return sizes[mid] if len(sizes) % 2 else (sizes[mid-1] + sizes[mid]) / 2


def _word_count(text: str) -> int:
    return len(text.split())


def _looks_like_title(
    text: str,
    ratio: float,
    page_max_ratio: float = 1.0,
) -> bool:
    """
    Prüft ob ein Block ein Titelkandidat ist.

    ratio ist relativ zur seiteninternen Verteilung:
    Ein Block gilt als Titelkandidat wenn er mindestens 50% des
    stärksten Elements auf seiner Seite erreicht.
    Absolute Schwellen werden vermieden — der Suchraum kommt
    vom DocumentTypeHint, nicht von diesem Filter.
    """
    if not text or len(text) < 4:
        return False
    if _NOT_TITLE_RE.match(text):
        return False
    if _word_count(text) > 30:
        return False
    if ratio > 15.0:  # Bild-Artefakt unabhängig von Seitennorm
        return False
    if page_max_ratio > 0 and ratio < page_max_ratio * 0.5:
        return False
    if _TOC_ENTRY_RE.search(text):
        return False
    return True


def _clean_title(text: str) -> str:
    return " ".join(text.split()).strip(".,:;")


def _clean_author_name(name: str) -> str | None:
    """Bereinigt einen Autornamen — gibt None zurück wenn kein gültiger Name."""
    # Enthält Ziffern → kein Personenname
    if re.search(r"\d", name):
        return None
    # Führende/nachfolgende Satzzeichen entfernen
    name = name.strip().strip(".,;:—–-")
    if len(name) < 3:
        return None
    # Nur Sonderzeichen → kein Name
    if not re.search(r"[A-Za-z\u00c0-\u024f]", name):
        return None
    return name


def _extract_authors_from_block(text: str) -> list[str]:
    text = _AUTHOR_PREFIX_RE.sub("", text).strip()
    parts = re.split(r"\s+(?:and|und|&)\s+|;\s*", text, flags=re.IGNORECASE)
    authors = []
    for part in parts:
        part = part.strip().strip(",")
        if not part or len(part) < 3:
            continue
        if re.search(r"\d{4}", part):
            continue
        if len(part.split()) > 6:
            continue
        cleaned = _clean_author_name(part)
        if cleaned:
            authors.append(cleaned)
    return authors


# Nicht-Namen: häufige Überschriften, Substantive, Phrasen die keine Namen sind
_NOT_NAME_WORDS_RE = re.compile(
    r"^\s*(?:summary|abstract|contents|introduction|impressum|collection|"
    r"overview|conclusion|discussion|results|methods|background|"
    r"zusammenfassung|einleitung|inhaltsverzeichnis|inhalt|"
    r"r[e\xe9]sum[e\xe9]|sommaire|foreword|preface|vorwort|"
    r"informing|managing|collapse|dereliction|providing|"
    r"this|these|the|a|an|in|on|at|by|of|to|for)\s*$",
    re.IGNORECASE,
)
# "and" zwischen Namen — aber nicht "and/or"
_NAME_AND_RE = re.compile(r"\b(?:and|und)\b(?!/)", re.IGNORECASE)


def _is_person_name_block(text: str) -> bool:
    """Prüft ob ein Block wahrscheinlich Personennamen enthält."""
    if not text or len(text) < 3:
        return False
    # Bekannte Nicht-Namen ausschließen
    if _NOT_NAME_WORDS_RE.match(text):
        return False
    # Genitiv auf Substantiv ("England's advice") → kein Personenname
    if re.search(r"\w+'s\s+\w+", text):
        return False
    # Gedankenstrich als Satztrenner → Fließtext-Fragment
    if re.search(r"\s[\u2013\u2014-]\s", text):
        return False
    # "and/or" → kein Autorenblock
    if re.search(r"\band/or\b", text, re.IGNORECASE):
        return False
    # Letztes Wort beginnt lowercase bei mehreren Wörtern → Fließtext-Fragment
    words = text.split()
    if len(words) > 1 and words[-1] and words[-1][0].islower():
        return False

    if _AUTHOR_PREFIX_RE.match(text):
        return True
    if _NAME_ABBREV_RE.search(text) and not _INSTITUTION_WORDS_RE.search(text):
        return True
    if _INSTITUTION_WORDS_RE.search(text):
        return False
    stripped = text.rstrip()
    if stripped.endswith(".") and not re.search(r"\b[A-Z]\.([A-Z]\.?)?\s*$", stripped):
        return False
    if re.match(r"^\d", text.strip()):
        return False
    if _PERSONAL_NAME_RE.search(text):
        if 1 <= len(words) <= 8:
            if _NAME_AND_RE.search(text):
                return True
            if len(words) == 1 and len(text.strip()) > 12:
                return False  # zu lang für einzelnen Nachnamen
            if len(words) <= 4:
                return True
    return False


# ---------------------------------------------------------------------------
# Identifier-Extraktion
# ---------------------------------------------------------------------------

def _scan_identifiers(
    blocks: list[dict],
) -> tuple[str | None, str | None, str | None, int | None]:
    doi = isbn = issn = None
    year = None
    for block in blocks:
        text = _block_text(block)
        if not text:
            continue
        if doi is None:
            m = _DOI_RE.search(text)
            if m:
                doi = m.group(1).rstrip(".")
        if isbn is None:
            m = _ISBN_RE.search(text)
            if m:
                raw = re.sub(r"[\s\-]", "", m.group(1))
                if len(raw) in (10, 13):
                    isbn = raw
        if issn is None:
            m = _ISSN_RE.search(text)
            if m:
                issn = m.group(1)
        if year is None:
            candidates = [int(y) for y in _YEAR_RE.findall(text)
                         if 1700 <= int(y) <= 2030]
            if candidates:
                year = max(candidates)
    return doi, isbn, issn, year


# ---------------------------------------------------------------------------
# Abstract-Extraktion
# ---------------------------------------------------------------------------

def _extract_abstract(blocks: list[dict]) -> tuple[str | None, float]:
    abstract_next = False
    for block in blocks:
        text = _block_text(block)
        if not text:
            continue
        first = _block_first_line(block)
        if abstract_next:
            if len(text) > 50:
                return text[:2000], 0.9
            abstract_next = False
        if ABSTRACT_RE.match(first):
            remainder = text[len(first):].strip()
            if len(remainder) > 50:
                return remainder[:2000], 0.95
            abstract_next = True
    return None, 0.0


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def extract_metadata(
    pdf_path: Path,
    profile,
    zones,
    body_text_profile,
    observations: list | None = None,
) -> ExtractedMetadata:
    """
    Extrahiert bibliografische Kernmetadaten.
    Nutzt DocumentTypeHint für dokumenttyp-spezifische Suchstrategien.
    """
    result = ExtractedMetadata()
    dom_size = body_text_profile.dominant_size if body_text_profile else 10.0

    hint = infer_document_type_hint(profile, zones, observations or [], pdf_path=pdf_path)
    logger.debug("metadata: doc_class=%s scan_cover=%s", hint.doc_class, hint.scan_cover)

    title_pages  = set(hint.title_search_pages)
    author_pages = set(hint.author_search_pages)
    id_pages     = set(list(zones.frontmatter_pages) + list(zones.body_pages[:2]))
    all_load     = sorted(title_pages | author_pages | id_pages)

    all_blocks: list[dict] = []
    title_candidate: tuple[float, str, int] | None = None
    author_blocks: list[str] = []

    # Pass 1: Titel-Kandidat finden
    with fitz.open(pdf_path) as doc:
        for page_idx in sorted(title_pages | id_pages):
            if page_idx >= len(doc):
                continue
            page = doc.load_page(page_idx)
            raw = page.get_text("rawdict")
            blocks = [b for b in raw.get("blocks", []) if b.get("type") == 0]

            if page_idx in id_pages:
                all_blocks.extend(blocks)

            if page_idx in title_pages:
                # page_max nur aus plausiblen Blöcken:
                # Bild-Artefakte (ratio>15 oder ratio>10+kurz) ausschließen
                page_ratios = []
                for _b in blocks:
                    _t = _block_text(_b)
                    if not _t:
                        continue
                    _r = _dominant_size(_b) / dom_size if dom_size > 0 else 1.0
                    if _r > 15.0:
                        continue
                    if _r > 10.0 and _word_count(_t) <= 6:
                        continue
                    page_ratios.append(_r)
                page_max = max(page_ratios) if page_ratios else 1.0

                for block in blocks:
                    text = _block_text(block)
                    if not text:
                        continue
                    size = _dominant_size(block)
                    ratio = size / dom_size if dom_size > 0 else 1.0
                    if _looks_like_title(text, ratio, page_max):
                        if (title_candidate is None
                                or ratio > title_candidate[0]
                                or (ratio >= title_candidate[0] * 0.95
                                    and page_idx < title_candidate[2])):
                            title_candidate = (ratio, text, page_idx)

    # Pass 2: Autoren nur auf Titel-Seite und nächster Seite suchen.
    # Dadurch werden Karten-Labels, TOC-Einträge etc. auf anderen Seiten
    # nicht als Autoren fehlklassifiziert.
    if title_candidate is not None:
        title_page_idx = title_candidate[2]
        author_scan = sorted(
            p for p in author_pages
            if title_page_idx <= p <= title_page_idx + 2
        )
        with fitz.open(pdf_path) as doc:
            for page_idx in author_scan:
                if page_idx >= len(doc):
                    continue
                page = doc.load_page(page_idx)
                raw = page.get_text("rawdict")
                blocks = [b for b in raw.get("blocks", []) if b.get("type") == 0]
                for block in blocks:
                    text = _block_text(block)
                    if not text or _word_count(text) > 20:
                        continue
                    size = _dominant_size(block)
                    ratio = size / dom_size if dom_size > 0 else 1.0
                    # Autorenblöcke sind nie kleiner als 70% des Fließtexts
                    # — filtert Kartenbezeichnungen, Bildunterschriften etc.
                    if ratio < 0.70:
                        continue
                    if _is_person_name_block(text):
                        author_blocks.extend(_extract_authors_from_block(text))

    if title_candidate:
        result.title = _clean_title(title_candidate[1])
        result.title_confidence = min(0.95, 0.5 + title_candidate[0] * 0.15)
        result.title_page = title_candidate[2]

    if author_blocks:
        seen: set[str] = set()
        unique = [a for a in author_blocks if a not in seen and not seen.add(a)]
        result.authors = unique[:8]
        result.authors_confidence = 0.7

    result.doi, result.isbn, result.issn, result.year = _scan_identifiers(all_blocks)
    result.abstract, result.abstract_confidence = _extract_abstract(all_blocks)

    logger.info(
        "metadata: title=%r conf=%.2f authors=%d doi=%s year=%s",
        result.title[:40] if result.title else None,
        result.title_confidence,
        len(result.authors),
        result.doi,
        result.year,
    )

    return result
