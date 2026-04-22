"""
atlas.parse.sections

Erkennt Überschriften und baut einen hierarchischen Section-Tree
direkt aus PyMuPDF-Blöcken — ohne SQLite-Zwischenspeicher.

Öffentliche API:
    sections = extract_sections(pdf_path, profile, zones, body_text_profile)
    sections: list[Section]

Bewährte Logik aus atlas.understanding (headings.py + section_tree.py):
- Nummerierungen als robustes Level-Signal (höchste Priorität)
- Typografisches Clustering für Level-Zuweisung
- Stack-basierter Tree-Aufbau mit Level-Jump-Korrektur
- Ausschluss-Filter: Formel-Labels, Captions, Referenz-Einträge etc.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf as fitz

from .logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Section:
    level: int
    title: str
    page_start: int
    page_end: int | None
    block_start: int        # Block-Index im Dokument (0-basiert)
    block_end: int | None
    source: str             # "numbered" | "typographic" | "backmatter"


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

# Nummerierungs-Pattern: "1.", "1.2", "1.2.3", "1.2.3.4"
_CHAPTER_NUM_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\s*\.?\s+\S"
)

# Filter für falsche Nummerierungen (Maßangaben, Bildlegenden, TOC-Einträge)
_UNIT_RE = re.compile(r'\b(?:in\.|mm|cm|m\b|ft|kg|lb)\b', re.IGNORECASE)
_YEAR_PERSON_RE = re.compile(r'\(\d{4}[-\u2013\u2014]\d{4}\)|\(\d{4}\)')
_CAPTION_NUM_INDICATORS = re.compile(
    r'\b(?:foto|photo|abb\.|abbildung|karte|zeichnung|'
    r'quelle|source|lkr\.|freilichtmuseum|verbreitungskarte|'
    r'portr\xe4t|gem\xe4lde|\xf6lgem\xe4lde)\b',
    re.IGNORECASE
)
_SPECIAL_CHARS_RE = re.compile(r'[<>\u2191\u2193\u2192\u2190\u223c~]')
_NUM_SENTENCE_STARTERS_RE = re.compile(
    r'^(?:der|die|das|ein|eine|eines|einem|einen|the|a|an|'
    r'this|that|these|those|his|her|its)\s',
    re.IGNORECASE
)

# Backmatter-Keywords (vereinfacht — vollständig in section_labels.py)
_BACKMATTER_RE = re.compile(
    r"^\s*(?:references?|bibliograph|literatur|appendix|anhang|"
    r"acknowledg|danksagung|index|glossar|glossary|"
    r"zusammenfassung|abstract|notes?)\s*$",
    re.IGNORECASE,
)

# Formel-Labels (aus text_patterns.py übernommen)
_FORMULA_LABEL_RE = re.compile(
    r"^\s*(?:given|solution|example|beispiel|aufgabe|lösung|"
    r"proof|beweis|theorem|lemma|corollary|definition|"
    r"remark|note|hinweis|anmerkung)"
    r"[\s:.\-–—]*(?:\d+[\.\d]*)?[\s:.\-–—]*$",
    re.IGNORECASE,
)

# Satzzeichen die auf Fließtext hinweisen
_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")

# Artikel/Pronomen/Präpositionen am Satzanfang
_SENTENCE_STARTERS = frozenset({
    "the", "a", "an", "his", "her", "its", "their", "our", "my",
    "for", "in", "at", "on", "by", "of", "to", "not", "one",
    "this", "that", "these", "those", "some", "both", "all",
    "der", "die", "das", "ein", "eine", "dem", "den", "des",
})


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


def _chapter_number_level(text: str) -> int | None:
    """Gibt Level aus validiertem Nummerierungsmuster zurück oder None."""
    m = _CHAPTER_NUM_RE.match(text)
    if not m:
        return None

    # Validierung: kein Maß, Bildlegende, TOC-Eintrag
    if _SPECIAL_CHARS_RE.search(text):
        return None
    rest = text[m.end():].strip()
    if not rest:
        return None
    if len(rest.split()) > 10:
        return None
    if _UNIT_RE.search(rest):
        return None
    if _YEAR_PERSON_RE.search(text):
        return None
    if _CAPTION_NUM_INDICATORS.search(text):
        return None
    if re.search(r'\s+\d{1,4}\s*$', text):
        return None
    if rest.startswith((',', '.')):
        return None
    if _NUM_SENTENCE_STARTERS_RE.match(rest):
        return None
    # Satz (endet mit Punkt + mehr als 4 Wörter) → kein Kapitel
    if _SENTENCE_END_RE.search(rest) and len(rest.split()) > 4:
        return None

    parts = m.group(1).split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return len(parts)


def _normalize_font_family(font_name: str) -> str:
    name = font_name
    if len(name) > 7 and name[6] == "+" and name[:6].isupper():
        name = name[7:]
    for suffix in ("-Bold", "-Italic", "-BoldItalic", "-Oblique",
                   "-BoldOblique", "-Regular", "-Medium", "-Light",
                   "-It", "-Bd", "-Rg", ",Bold", ",Italic"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name


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


def _block_props(block: dict) -> dict:
    """Extrahiert typografische Eigenschaften eines Blocks."""
    sizes: list[float] = []
    bold_chars = italic_chars = total_chars = 0
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
            if flags & 16:
                bold_chars += n
            if flags & 2:
                italic_chars += n
            font = span.get("font", "")
            if font:
                fam = _normalize_font_family(font)
                font_counts[fam] = font_counts.get(fam, 0) + n
            color = int(span.get("color", 0))
            color_counts[color] = color_counts.get(color, 0) + n

    if not sizes:
        return {"size": 0.0, "bold_ratio": 0.0, "italic_ratio": 0.0,
                "font_family": "", "color": 0, "all_caps": False}

    sizes.sort()
    mid = len(sizes) // 2
    dom_size = sizes[mid] if len(sizes) % 2 else (sizes[mid-1] + sizes[mid]) / 2
    total = max(1, total_chars)
    dom_font = max(font_counts, key=font_counts.get) if font_counts else ""
    dom_color = max(color_counts, key=color_counts.get) if color_counts else 0

    # all_caps: alle alpha-Zeichen sind Großbuchstaben
    raw = "".join(
        _span_text(sp)
        for line in block.get("lines", [])
        for sp in line.get("spans", [])
    )
    alpha = [c for c in raw if c.isalpha()]
    all_caps = len(alpha) >= 3 and all(c.isupper() for c in alpha)

    return {
        "size":        dom_size,
        "bold_ratio":  bold_chars / total,
        "italic_ratio": italic_chars / total,
        "font_family": dom_font,
        "color":       dom_color,
        "all_caps":    all_caps,
    }


# ---------------------------------------------------------------------------
# Ausschluss-Filter
# ---------------------------------------------------------------------------

def _is_formula_label(text: str) -> bool:
    return bool(_FORMULA_LABEL_RE.match(text))


def _is_caption_like(text: str) -> bool:
    tl = text.lower().strip()
    return any(tl.startswith(p) for p in (
        "figure ", "fig. ", "fig ", "table ", "tab. ",
        "abb. ", "abbildung ", "tabelle ", "plate ",
        "image ", "photo ", "grafik ", "karte ", "tafel ",
    ))


def _is_reference_entry(text: str, italic: bool = False) -> bool:
    """Grober Filter für Literaturangaben."""
    if len(text.split()) < 5:
        return False
    # Enthält Jahr in Klammern → Literaturangabe
    if re.search(r"\(\d{4}\)", text):
        return True
    # Endet mit Seitenzahl-Muster
    if re.search(r",\s*pp?\.\s*\d+", text, re.IGNORECASE):
        return True
    return False


def _is_sentence_heading(text: str) -> bool:
    """Vollständiger Satz → kein Heading."""
    words = text.split()
    if len(words) < 6:
        return False
    return bool(_SENTENCE_END_RE.search(text)) and len(words) > 8


def _is_letter_spaced(text: str) -> bool:
    """Erkennt letter-spaced Text: "R O B I N  T A I T" → True."""
    # Mindestens 4 Wörter, die meisten sind Einzelbuchstaben
    words = text.split()
    if len(words) < 4:
        return False
    single_chars = sum(1 for w in words if len(w) == 1)
    return single_chars / len(words) >= 0.6


def _is_fragment(text: str, size_ratio: float, italic: bool) -> bool:
    """Einzelne Wörter oder sehr kurze Fragmente die kein Heading sind."""
    words = text.split()
    if len(words) == 1 and text[0].isupper() and not text.isupper() and len(text) > 3:
        return True  # einzelnes Wort mit Großbuchstabe → Fließtext-Fragment
    if (len(words) == 2 and words[0].lower() in _SENTENCE_STARTERS
            and len(words[1]) > 1 and words[1][0].islower()):
        return True  # "The X" → Fließtext
    if _is_letter_spaced(text):
        return True  # "R O B I N" → letter-spaced Dekotext
    return False


# ---------------------------------------------------------------------------
# Heading-Score
# ---------------------------------------------------------------------------

def _heading_score(
    props: dict,
    text: str,
    dom_size: float,
    body_color: int,
    body_family: str,
) -> float:
    """
    Berechnet einen Heading-Score für einen Block.

    0.0 = kein Heading-Kandidat
    > 0.0 = Kandidat mit diesem Score

    Direkt aus signals.py übernommene Logik, vereinfacht für
    direkte Block-Analyse ohne SQLite-Zwischenspeicher.
    """
    size = props["size"]
    if size <= 0 or dom_size <= 0:
        return 0.0

    ratio = size / dom_size

    # Bildtext-Artefakt: extrem groß + kurzer Text
    if ratio > 10.0 and len(text.split()) <= 6:
        return 0.0
    if ratio > 15.0:
        return 0.0
    bold = props["bold_ratio"] > 0.5
    italic = props["italic_ratio"] > 0.5
    all_caps = props["all_caps"]
    font_family = props["font_family"]
    color = props["color"]

    words = text.split()
    word_count = len(words)

    # Basis: typografische Auszeichnung
    # Größer als Fließtext
    size_signal = min(1.0, max(0.0, (ratio - 1.0) / 0.5))  # 0 bei 1.0x, 1.0 bei 1.5x+

    # Bold
    bold_signal = 0.7 if bold else 0.0

    # Andere Font-Familie als Fließtext
    family_signal = 0.5 if (font_family and body_family and
                             font_family != body_family) else 0.0

    # All-Caps
    caps_signal = 0.6 if all_caps else 0.0

    # Farbig (nicht Schwarz/Dunkelgrau)
    r_c = (color >> 16) & 0xFF
    g_c = (color >> 8) & 0xFF
    b_c = color & 0xFF
    color_signal = (0.5 if (color != body_color and
                             not (r_c < 80 and g_c < 80 and b_c < 80))
                    else 0.0)

    # Italic-Malus
    italic_penalty = -0.2 if italic and not bold else 0.0

    # Kombiniere: mindestens ein starkes Signal nötig
    typo_signal = max(size_signal * 0.9,
                      bold_signal * (0.8 if ratio >= 1.05 else 0.3),
                      family_signal,
                      caps_signal * 0.7)

    if typo_signal < 0.15:
        return 0.0  # keine typografische Auszeichnung

    # Form-Signal: kurzer Text, endet nicht mit Punkt
    short = 1.0 if word_count <= 12 else max(0.0, (20 - word_count) / 8)
    no_sentence_end = 0.0 if _SENTENCE_END_RE.search(text) and word_count > 5 else 1.0
    form_signal = short * no_sentence_end

    score = typo_signal * form_signal + color_signal + italic_penalty
    score = max(0.0, min(1.0, score))

    return score


# ---------------------------------------------------------------------------
# Style-Model für Level-Zuweisung
# ---------------------------------------------------------------------------

def _build_style_model(candidates: list[dict]) -> dict[tuple, int]:
    """
    Clustert Heading-Kandidaten nach Typografie und weist Levels zu.

    Vereinfachte Version aus understanding/core/style_model.py:
    - Key: (size_bucket, bold, italic, all_caps)
    - Sortiert nach Größe absteigend → L1, L2, L3, ...
    """
    if not candidates:
        return {}

    style_counts: dict[tuple, list[float]] = {}
    for c in candidates:
        props = c["props"]
        size = props["size"]
        bold = props["bold_ratio"] > 0.5
        italic = props["italic_ratio"] > 0.5
        all_caps = props["all_caps"]
        # Größe in 0.5pt-Buckets runden für Clustering
        size_bucket = round(size * 2) / 2
        key = (size_bucket, bold, italic, all_caps)
        style_counts.setdefault(key, []).append(size)

    # Sortiere nach dominanter Größe absteigend
    sorted_styles = sorted(
        style_counts.keys(),
        key=lambda k: (-k[0], not k[1], k[2]),  # größer + bold zuerst
    )

    return {style: i + 1 for i, style in enumerate(sorted_styles)}


def _style_key(props: dict) -> tuple:
    size = round(props["size"] * 2) / 2
    bold = props["bold_ratio"] > 0.5
    italic = props["italic_ratio"] > 0.5
    all_caps = props["all_caps"]
    return (size, bold, italic, all_caps)


# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def _load_blocks(pdf_path: Path, page_indices: list[int]) -> list[dict]:
    """Lädt alle Blöcke der angegebenen Seiten mit Block-Index."""
    blocks_out: list[dict] = []
    block_index = 0
    with fitz.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            if page_idx not in set(page_indices):
                # Übersprungene Seiten: Block-Index trotzdem hochzählen
                page = doc.load_page(page_idx)
                raw = page.get_text("rawdict")
                for b in raw.get("blocks", []):
                    if b.get("type") == 0:
                        block_index += 1
                continue
            page = doc.load_page(page_idx)
            raw = page.get_text("rawdict")
            for b in raw.get("blocks", []):
                if b.get("type") != 0:
                    continue
                b["_block_index"] = block_index
                b["_page_index"] = page_idx
                blocks_out.append(b)
                block_index += 1
    return blocks_out


def _load_all_blocks(
    pdf_path: Path,
    header_y1: float | None = None,
    footer_y0: float | None = None,
) -> list[dict]:
    """
    Lädt alle Blöcke mit globalem Block-Index.

    header_y1 / footer_y0: Blöcke in Header/Footer-Bändern werden
    mit _in_furniture=True markiert und beim Heading-Scan gefiltert.
    """
    blocks_out: list[dict] = []
    block_index = 0
    with fitz.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            raw = page.get_text("rawdict")
            for b in raw.get("blocks", []):
                if b.get("type") != 0:
                    block_index += 1
                    continue
                b["_block_index"] = block_index
                b["_page_index"] = page_idx
                # Header/Footer-Band-Markierung
                y0 = b.get("bbox", [0, 0, 0, 0])[1]
                y1 = b.get("bbox", [0, 0, 0, 999])[3]
                in_header = header_y1 is not None and y1 <= header_y1 * 1.05
                in_footer = footer_y0 is not None and y0 >= footer_y0 * 0.95
                b["_in_furniture"] = in_header or in_footer
                blocks_out.append(b)
                block_index += 1
    return blocks_out


def _build_repeated_texts(
    pdf_path: Path,
    page_count: int,
    sample_pages: int = 60,
    min_repeat_ratio: float = 0.12,
    max_words: int = 8,
) -> frozenset[str]:
    """
    Findet kurze Texte die auf vielen Seiten wiederholt vorkommen.
    Schwelle: ≥12% der Probe-Seiten (= 7x bei 60 Seiten).
    """
    n_sample = min(sample_pages, page_count)
    text_pages: dict[str, set[int]] = {}

    with fitz.open(pdf_path) as doc:
        for page_idx in range(n_sample):
            page = doc.load_page(page_idx)
            raw = page.get_text("rawdict")
            for b in raw.get("blocks", []):
                if b.get("type") != 0:
                    continue
                text = _block_text(b).strip()
                if not text or len(text) < 3:
                    continue
                if len(text.split()) > max_words:
                    continue
                text_pages.setdefault(text, set()).add(page_idx)

    threshold = max(3, int(n_sample * min_repeat_ratio))
    repeated = frozenset(
        t for t, pages in text_pages.items()
        if len(pages) >= threshold
    )
    logger.debug("sections: %d repeated texts (threshold=%d/%d)",
                 len(repeated), threshold, n_sample)
    return repeated


def extract_sections(
    pdf_path: Path,
    profile,
    zones,
    body_text_profile,
    doc_hint=None,
    max_level: int | None = None,
) -> list[Section]:
    """
    Extrahiert den hierarchischen Section-Tree aus einem PDF.

    Strategie (in Priorität):
    1. Nummerierte Überschriften (chapter_number_level) — robustestes Signal
    2. Backmatter-Keywords → immer L1
    3. Typografisches Clustering (style_model) → Level aus Font-Eigenschaften

    Ausschlüsse: Formel-Labels, Captions, Referenz-Einträge,
    Satz-Fragmente, Running Headers.

    Gibt leere Liste zurück bei Scan-PDFs (kein nativer Text).
    """
    dom_size = body_text_profile.dominant_size if body_text_profile else 0.0
    if dom_size <= 0:
        logger.debug("sections: Scan-PDF (dom_size=0), kein Section-Tree")
        return []

    # max_level: Tiefenbegrenzung für Keyword-Extraktion und Navigation.
    # Unterhalb dieser Ebene stehen typischerweise Glossareinträge und
    # Detaildefinitionen die für Abschnitts-Keywords nicht relevant sind.
    if max_level is None:
        doc_class = getattr(doc_hint, "doc_class", "article") if doc_hint else "article"
        max_level = {"article": 4, "report": 4, "book": 4, "collection": 3}.get(
            doc_class, 4
        )

    body_color  = (body_text_profile.dominant_color
                   if body_text_profile else 0)
    body_family = (body_text_profile.dominant_font_family
                   if body_text_profile else "")

    # Suche in Body + Backmatter, nicht in Frontmatter
    body_pages = set(zones.body_pages)
    back_pages = set(
        getattr(zones, "backmatter_pages", [])
    )
    search_pages = sorted(body_pages | back_pages)

    if not search_pages:
        search_pages = list(range(profile.page_count))

    logger.debug("sections: scanning %d pages (body=%d back=%d)",
                 len(search_pages), len(body_pages), len(back_pages))

    fp = profile.furniture_profile
    header_y1 = fp.header_band.y1 if fp and fp.header_band else None
    footer_y0 = fp.footer_band.y0 if fp and fp.footer_band else None
    blocks = _load_all_blocks(pdf_path, header_y1=header_y1, footer_y0=footer_y0)

    # Pre-Pass: wiederholte Texte als Running Headers erkennen
    repeated_texts = _build_repeated_texts(pdf_path, profile.page_count)

    # --- Pass 1: Kandidaten sammeln ---
    candidates: list[dict] = []
    for block in blocks:
        page_idx = block["_page_index"]
        if page_idx not in set(search_pages):
            continue

        # Running Header/Footer überspringen
        if block.get("_in_furniture"):
            continue

        text = _block_text(block)
        if not text or len(text) < 3:
            continue
        if text in repeated_texts:
            continue

        words = text.split()

        # Schnelle Ausschlüsse
        # Sonderzeichen (Pfeile, Tilde) → kein Heading
        if _SPECIAL_CHARS_RE.search(text):
            continue
        if _is_formula_label(text):
            continue
        if _is_caption_like(text):
            continue
        if _is_sentence_heading(text):
            continue
        if _is_reference_entry(text):
            continue
        if len(words) > 25:
            continue

        # Nummerierung prüft zuerst — kein Score-Cutoff nötig
        num_level = _chapter_number_level(text)
        is_backmatter = bool(_BACKMATTER_RE.match(text))

        props = _block_props(block)
        score = _heading_score(props, text, dom_size, body_color, body_family)

        if num_level is not None:
            # Nummerierte Überschrift: Score-Cutoff.
            # score=0.0 bedeutet Bild-Artefakt (ratio>10+kurz) → immer ausschließen
            if score <= 0.0:
                continue
            if score >= 0.10 or num_level <= 2:
                candidates.append({
                    "block":      block,
                    "text":       text,
                    "props":      props,
                    "score":      max(score, 0.3),
                    "num_level":  num_level,
                    "backmatter": is_backmatter,
                    "page":       page_idx,
                    "block_index": block["_block_index"],
                })
        elif is_backmatter:
            candidates.append({
                "block":      block,
                "text":       text,
                "props":      props,
                "score":      0.8,
                "num_level":  None,
                "backmatter": True,
                "page":       page_idx,
                "block_index": block["_block_index"],
            })
        elif score >= 0.35:
            if _is_fragment(text, props["size"] / dom_size, props["italic_ratio"] > 0.5):
                continue
            candidates.append({
                "block":      block,
                "text":       text,
                "props":      props,
                "score":      score,
                "num_level":  None,
                "backmatter": False,
                "page":       page_idx,
                "block_index": block["_block_index"],
            })

    candidates.sort(key=lambda c: c["block_index"])
    logger.debug("sections: %d Kandidaten nach Pass 1", len(candidates))

    if not candidates:
        return []

    # --- Pass 2: Style-Model für Level-Zuweisung ---
    body_cands = [c for c in candidates
                  if not c["backmatter"] and c["num_level"] is None]
    style_levels = _build_style_model(body_cands)

    # --- Pass 3: Level-Zuweisung und Tree-Aufbau ---
    sections: list[Section] = []
    stack: list[dict] = []  # {"level": int, "section_idx": int}

    for c in candidates:
        text = c["text"]
        page = c["page"]
        block_index = c["block_index"]
        props = c["props"]

        # Level bestimmen
        if c["num_level"] is not None:
            level = c["num_level"]
            source = "numbered"
        elif c["backmatter"]:
            level = 1
            source = "backmatter"
            stack = []  # Backmatter-Ankerpunkte starten immer von oben
        else:
            sk = _style_key(props)
            level = style_levels.get(sk, 1)
            source = "typographic"

            # Italic + kurz → min L2
            if props["italic_ratio"] > 0.5 and len(text.split()) <= 6:
                level = max(level, 2)

        # Stack-basierter Tree-Aufbau
        if c["backmatter"]:
            stack = []
        else:
            while stack and stack[-1]["level"] >= level:
                stack.pop()

        # parent bestimmt ob wir an der richtigen Stelle sind
        if not stack:
            level = 1  # erste Ebene ohne Parent ist immer L1
        else:
            parent_level = stack[-1]["level"]
            if level > parent_level + 1:
                level = parent_level + 1  # kein Level-Jump > 1

        # Tiefenbegrenzung: Einträge unterhalb max_level überspringen
        if level > max_level:
            continue

        section = Section(
            level=level,
            title=text,
            page_start=page,
            page_end=None,
            block_start=block_index,
            block_end=None,
            source=source,
        )
        sections.append(section)
        stack.append({"level": level, "section_idx": len(sections) - 1})

    # page_end / block_end aus Nachfolger berechnen
    for i, sec in enumerate(sections):
        if i + 1 < len(sections):
            nxt = sections[i + 1]
            sec.page_end = nxt.page_start
            sec.block_end = nxt.block_start
        else:
            sec.page_end = profile.page_count - 1
            sec.block_end = None

    logger.info("sections: %d Sektionen extrahiert aus %s",
                len(sections), pdf_path.name)

    return sections
