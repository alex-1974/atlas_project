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
# "prepared by Name", "written by Name" etc. innerhalb eines Satzes
_INLINE_BY_RE = re.compile(
    r"(?:prepared|written|authored|compiled|edited|created)\s+by\s+(.+?)(?:\.|$)",
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
# Signal-Modell und Reconciliation
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MetadataSignal:
    """Ein einzelnes Metadaten-Signal mit Quelle und Rohkonfidenz."""
    value: str
    source: str         # "pdf_meta" | "typography" | "crossref"
    confidence: float   # 0.0–1.0 Rohkonfidenz dieser Quelle


_PDF_META_BAD_TITLE_RE = re.compile(
    r"(?:microsoft\s+word|openoffice|libreoffice|latex|adobe|acrobat"
    r"|untitled|unknown|document\d*|temp|draft"
    r"|\.(?:pdf|doc|docx|odt|tex)$"
    r"|^[A-Z]:\\|^/home/|^/tmp/)",
    re.IGNORECASE,
)

_PDF_META_BAD_AUTHOR_RE = re.compile(
    r"^(?:unknown|user|admin|author|owner|root|default"
    r"|microsoft|adobe|apple|openoffice|libreoffice"
    r"|scanner|scan|digitized?|converted?)$",
    re.IGNORECASE,
)


def _fuzzy_match(a: str, b: str) -> float:
    """
    Einfache Fuzzy-Ähnlichkeit zwischen zwei Strings.
    Normalisiert: lowercase, whitespace kollabiert.
    Gibt Jaccard-Ähnlichkeit auf Wort-Ebene zurück.
    """
    def _tokens(s: str) -> set[str]:
        return set(re.sub(r"[^\w\s]", "", s.lower()).split())

    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _extract_pdf_meta_signals(doc: fitz.Document) -> tuple[MetadataSignal | None, list[MetadataSignal]]:
    """
    Extrahiert Titel und Autoren aus PDF-Metadaten (Info-Dict + XMP).

    Gibt (title_signal | None, [author_signals]) zurück.
    Filtert offensichtlich fehlerhafte Metadaten.
    """
    meta = doc.metadata or {}

    # Titel
    title_signal: MetadataSignal | None = None
    raw_title = (meta.get("title") or "").strip()
    if (raw_title
            and len(raw_title) >= 5
            and len(raw_title) <= 300
            and not _PDF_META_BAD_TITLE_RE.search(raw_title)):
        # Konfidenz basierend auf Plausibilität
        word_count = len(raw_title.split())
        conf = 0.55
        if 3 <= word_count <= 20:
            conf = 0.65  # typische Titellänge
        if word_count > 20:
            conf = 0.45  # zu lang, vielleicht automatisch generiert
        title_signal = MetadataSignal(
            value=raw_title,
            source="pdf_meta",
            confidence=conf,
        )

    # Autoren
    author_signals: list[MetadataSignal] = []
    _PERSON_LIKE_RE = re.compile(
        r"[A-Z\u00C0-\u024F][a-z\u00E0-\u024F]{1,}"
    )
    raw_author = (meta.get("author") or "").strip()
    if (raw_author
            and not _PDF_META_BAD_AUTHOR_RE.match(raw_author)
            and _PERSON_LIKE_RE.search(raw_author)):
        # Aufteilen auf Trennzeichen
        parts = re.split(r";\s*|,\s*(?=[A-Z\u00c0-\u024f])", raw_author)
        for part in parts:
            part = part.strip()
            if len(part) >= 3 and not _PDF_META_BAD_AUTHOR_RE.match(part):
                author_signals.append(MetadataSignal(
                    value=part,
                    source="pdf_meta",
                    confidence=0.55,
                ))

    return title_signal, author_signals


def _reconcile_title(
    typo_signal: MetadataSignal | None,
    pdf_signal: MetadataSignal | None,
) -> tuple[str | None, float]:
    """
    Kreuzvalidiert typografischen und PDF-Metadaten-Titel.

    Übereinstimmung erhöht die Konfidenz beider Quellen.
    Widerspruch → bessere Quelle gewinnt, aber mit Abzug.
    """
    if typo_signal is None and pdf_signal is None:
        return None, 0.0

    if typo_signal is None:
        return pdf_signal.value, pdf_signal.confidence

    if pdf_signal is None:
        return typo_signal.value, typo_signal.confidence

    sim = _fuzzy_match(typo_signal.value, pdf_signal.value)

    if sim >= 0.80:
        # Starke Übereinstimmung → beide bestätigen sich
        value = typo_signal.value  # typografischer Titel bevorzugt (Originalformatierung)
        conf = min(0.97, max(typo_signal.confidence, pdf_signal.confidence) + 0.20)
        logger.debug("title reconcile: match=%.2f → conf=%.2f '%s'", sim, conf, value[:50])
        return value, conf

    if sim >= 0.40:
        # Teilweise Übereinstimmung — könnte Untertitel-Variation sein
        value = typo_signal.value
        conf = min(0.80, max(typo_signal.confidence, pdf_signal.confidence) + 0.10)
        logger.debug("title reconcile: partial=%.2f → conf=%.2f '%s'", sim, conf, value[:50])
        return value, conf

    # Widerspruch: beste Quelle gewinnt, aber mit leichtem Abzug
    if typo_signal.confidence >= pdf_signal.confidence:
        conf = max(0.30, typo_signal.confidence - 0.05)
        logger.debug("title reconcile: conflict, typo wins conf=%.2f '%s'", conf, typo_signal.value[:50])
        return typo_signal.value, conf
    else:
        conf = max(0.30, pdf_signal.confidence - 0.05)
        logger.debug("title reconcile: conflict, pdf wins conf=%.2f '%s'", conf, pdf_signal.value[:50])
        return pdf_signal.value, conf


def _reconcile_authors(
    typo_authors: list[str],
    pdf_signals: list[MetadataSignal],
) -> tuple[list[str], float]:
    """
    Kreuzvalidiert typografisch und aus PDF-Metadaten extrahierte Autoren.
    """
    if not typo_authors and not pdf_signals:
        return [], 0.0

    if not pdf_signals:
        return typo_authors, 0.7

    pdf_names = [s.value for s in pdf_signals]

    if not typo_authors:
        return pdf_names, 0.55

    # Prüfe Überschneidung
    matches = sum(
        1 for ta in typo_authors
        for ps in pdf_signals
        if _fuzzy_match(ta, ps.value) >= 0.60
    )

    if matches > 0:
        # Übereinstimmung → typografische Liste bevorzugen (vollständiger)
        # aber Konfidenz erhöhen
        conf = min(0.92, 0.70 + matches * 0.08)
        return typo_authors, conf

    # Kein Overlap — beide als Kandidaten, typografisch bevorzugt
    # (weniger fehlerhafte Metadaten-Kodierung)
    return typo_authors, 0.65




# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ExtractedMetadata:
    title: str | None = None
    title_confidence: float = 0.0
    title_page: int | None = None
    title_source: str | None = None       # "typography" | "pdf_meta" | "reconciled"
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


def _normalize_font_family(font_name: str) -> str:
    name = font_name
    if len(name) > 7 and name[6] == '+' and name[:6].isupper():
        name = name[7:]
    for suffix in ('-Bold', '-Italic', '-BoldItalic', '-Oblique',
                   '-BoldOblique', '-Regular', '-Medium', '-Light',
                   '-It', '-Bd', '-Rg', ',Bold', ',Italic'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name


def _block_typography(block: dict) -> dict:
    """
    Extrahiert typografische Eigenschaften eines Blocks auf Span-Ebene.

    Gibt zurück:
        size        dominante Schriftgröße (Median)
        bold_ratio  Anteil bold-Spans (gewichtet nach Zeichenanzahl)
        italic_ratio Anteil italic-Spans
        font_family normalisierter Font-Familienname (dominanter Span)
        color       dominante Textfarbe (RGB integer)
    """

    sizes: list[float] = []
    bold_chars = 0
    italic_chars = 0
    total_chars = 0
    font_counts: dict[str, int] = {}
    color_counts: dict[int, int] = {}

    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = _span_text(span).strip()
            if not t:
                continue
            n = len(t)
            total_chars += n

            size = float(span.get("size", 0.0))
            if size > 0:
                sizes.append(size)

            flags = span.get("flags", 0)
            if flags & 16:   # bold
                bold_chars += n
            if flags & 2:    # italic
                italic_chars += n

            font = span.get("font", "")
            if font:
                fam = _normalize_font_family(font)
                font_counts[fam] = font_counts.get(fam, 0) + n

            color = int(span.get("color", 0))
            color_counts[color] = color_counts.get(color, 0) + n

    if not sizes:
        return {"size": 0.0, "bold_ratio": 0.0, "italic_ratio": 0.0,
                "font_family": "", "color": 0}

    sizes.sort()
    mid = len(sizes) // 2
    dom_size = sizes[mid] if len(sizes) % 2 else (sizes[mid-1] + sizes[mid]) / 2

    total = max(1, total_chars)
    dom_font = max(font_counts, key=font_counts.get) if font_counts else ""
    dom_color = max(color_counts, key=color_counts.get) if color_counts else 0

    return {
        "size": dom_size,
        "bold_ratio": bold_chars / total,
        "italic_ratio": italic_chars / total,
        "font_family": dom_font,
        "color": dom_color,
    }


def _title_score(
    text: str,
    ratio: float,
    page_max_ratio: float,
    typo: dict,
    body_profile,
) -> float:
    """
    Konfidenz-Score für einen Titelkandidaten (0.0 = kein Kandidat).

    Hauptsignal: Größenverhältnis zur Seiten-Norm.
    Boosts: bold, andere Font-Familie als Fließtext, farbiger Text.
    Abzug: kursiv (Titel selten italic).
    """
    if not text or len(text) < 4:
        return 0.0
    if _NOT_TITLE_RE.match(text):
        return 0.0
    if _word_count(text) > 30:
        return 0.0
    if ratio > 15.0:
        return 0.0
    if ratio > 10.0 and _word_count(text) <= 6:
        return 0.0
    if page_max_ratio > 0 and ratio < page_max_ratio * 0.5:
        return 0.0
    if _TOC_ENTRY_RE.search(text):
        return 0.0

    # Basis-Score
    score = min(1.0, ratio / max(1.0, page_max_ratio))

    # Bold-Boost
    if typo.get("bold_ratio", 0.0) > 0.5:
        score = min(1.0, score + 0.08)

    if body_profile is not None:
        # Andere Font-Familie als Fließtext
        body_family = getattr(body_profile, "dominant_font_family", "") or ""
        block_family = typo.get("font_family", "")
        if block_family and body_family and block_family != body_family:
            score = min(1.0, score + 0.05)

        # Farbiger Text (nicht schwarz/dunkelgrau)
        body_color = getattr(body_profile, "dominant_color", 0) or 0
        block_color = typo.get("color", 0)
        if block_color != body_color:
            r = (block_color >> 16) & 0xFF
            g = (block_color >> 8) & 0xFF
            b = block_color & 0xFF
            if not (r < 80 and g < 80 and b < 80):
                score = min(1.0, score + 0.04)

    # Italic-Abzug
    if typo.get("italic_ratio", 0.0) > 0.5:
        score = max(0.0, score - 0.05)

    return score


def _author_typo_score(typo: dict, title_ratio: float, dom_size: float) -> float:
    """
    Plausibilitäts-Score für einen Autoren-Block (0.0 = nicht plausibel).

    Autoren sind typischerweise:
    - Kleiner als der Titel, aber >= 70% des Fließtexts
    - Manchmal italic (Zeitschriften-Konvention)
    - Selten bold (Titel sind bold, nicht Autoren)
    """
    size = typo.get("size", 0.0)
    if dom_size <= 0 or size <= 0:
        return 0.5  # keine Info → neutral
    ratio = size / dom_size

    if ratio < 0.70:
        return 0.0  # zu klein (Kartenbeschriftungen, Fußnoten)
    if ratio > title_ratio * 1.1:
        return 0.0  # größer als Titel → kein Autor

    score = 0.6  # Basis

    if typo.get("italic_ratio", 0.0) > 0.5:
        score = min(1.0, score + 0.15)  # italic → wahrscheinlicher Autor

    if typo.get("bold_ratio", 0.0) > 0.5:
        score = max(0.0, score - 0.10)  # bold → eher Überschrift

    return score


def _looks_like_title(text: str, ratio: float, page_max_ratio: float = 1.0) -> bool:
    """Boolean-Wrapper um _title_score für page_max-Berechnung."""
    if not text or len(text) < 4:
        return False
    if _NOT_TITLE_RE.match(text):
        return False
    if _word_count(text) > 30:
        return False
    if ratio > 15.0:
        return False
    if ratio > 10.0 and _word_count(text) <= 6:
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
    # Inline-By-Muster: "prepared by David Pickles and Jeremy Lake"
    m = _INLINE_BY_RE.search(text)
    if m:
        text = m.group(1).strip()
    else:
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

def _extract_metadata_scan_fallback(
    pdf_path: Path,
    all_blocks: list[dict],
) -> ExtractedMetadata:
    """
    Fallback für Scan-PDFs ohne nativen Text.
    Nutzt ausschließlich PDF-Metadaten.
    """
    result = ExtractedMetadata()
    with fitz.open(pdf_path) as doc:
        pdf_title_signal, pdf_author_signals = _extract_pdf_meta_signals(doc)

    if pdf_title_signal:
        result.title = pdf_title_signal.value
        result.title_confidence = pdf_title_signal.confidence
        result.title_source = "pdf_meta"

    if pdf_author_signals:
        result.authors = [s.value for s in pdf_author_signals][:8]
        result.authors_confidence = 0.50

    result.doi, result.isbn, result.issn, result.year = _scan_identifiers(all_blocks)

    logger.info(
        "metadata (scan-fallback): title=%r conf=%.2f",
        result.title[:40] if result.title else None,
        result.title_confidence,
    )
    return result


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

    Wenn kein nativer Text vorhanden (Scan-PDF), Fallback auf
    PDF-Metadaten-only via _extract_metadata_scan_fallback().
    """
    result = ExtractedMetadata()

    # Scan-Erkennung: kein stabiles Body-Text-Profil → kein dom_size
    dom_size = body_text_profile.dominant_size if body_text_profile else 0.0
    is_scan = dom_size <= 0.0

    if is_scan:
        logger.info("metadata: Scan-PDF erkannt (dom_size=0), Fallback auf PDF-Metadaten")
        # Identifier noch aus Textblöcken lesen falls vorhanden
        all_blocks: list[dict] = []
        id_pages = set(list(zones.frontmatter_pages) + list(zones.body_pages[:2]))
        with fitz.open(pdf_path) as doc:
            for page_idx in sorted(id_pages):
                if page_idx >= len(doc):
                    continue
                raw = doc.load_page(page_idx).get_text("rawdict")
                all_blocks.extend(
                    b for b in raw.get("blocks", []) if b.get("type") == 0
                )
        return _extract_metadata_scan_fallback(pdf_path, all_blocks)

    hint = infer_document_type_hint(profile, zones, observations or [], pdf_path=pdf_path)
    logger.debug("metadata: doc_class=%s scan_cover=%s", hint.doc_class, hint.scan_cover)

    title_pages  = set(hint.title_search_pages)
    author_pages = set(hint.author_search_pages)
    id_pages     = set(list(zones.frontmatter_pages) + list(zones.body_pages[:2]))
    all_load     = sorted(title_pages | author_pages | id_pages)

    all_blocks = []
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
                    typo = _block_typography(block)
                    score = _title_score(text, ratio, page_max, typo, body_text_profile)
                    if score > 0.0:
                        if (title_candidate is None
                                or score > title_candidate[0]
                                or (score >= title_candidate[0] * 0.95
                                    and page_idx < title_candidate[2])):
                            title_candidate = (score, text, page_idx)

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
                title_ratio = title_candidate[0] if title_candidate else 2.0
                for block in blocks:
                    text = _block_text(block)
                    if not text or _word_count(text) > 20:
                        continue
                    typo = _block_typography(block)
                    auth_score = _author_typo_score(typo, title_ratio, dom_size)
                    if auth_score <= 0.0:
                        continue
                    if _is_person_name_block(text):
                        author_blocks.extend(_extract_authors_from_block(text))

    # --- PDF-Metadaten lesen und Signale aufbauen ---
    with fitz.open(pdf_path) as doc:
        pdf_title_signal, pdf_author_signals = _extract_pdf_meta_signals(doc)

    # Typografisches Titel-Signal
    typo_title_signal: MetadataSignal | None = None
    if title_candidate:
        raw_conf = min(0.92, 0.5 + title_candidate[0] * 0.45)
        typo_title_signal = MetadataSignal(
            value=_clean_title(title_candidate[1]),
            source="typography",
            confidence=raw_conf,
        )
        result.title_page = title_candidate[2]

    # Reconciliation: Titel
    result.title, result.title_confidence = _reconcile_title(
        typo_title_signal, pdf_title_signal
    )
    if result.title:
        if typo_title_signal and pdf_title_signal:
            result.title_source = "reconciled"
        elif typo_title_signal:
            result.title_source = "typography"
        else:
            result.title_source = "pdf_meta"

    # Typografische Autoren deduplizieren
    seen: set[str] = set()
    typo_authors = [
        a for a in author_blocks
        if a not in seen and not seen.add(a)  # type: ignore[func-returns-value]
    ][:8]

    # Reconciliation: Autoren
    result.authors, result.authors_confidence = _reconcile_authors(
        typo_authors, pdf_author_signals
    )

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
