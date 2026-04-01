# src/atlas/understanding/core/text_patterns.py
"""Shared text-pattern functions for the Atlas DU pipeline.

Single home for every heuristic that inspects block text. Previously
spread across heading_normalization.py, heading_candidates.py, roles.py,
zones.py, and signals.py with slightly divergent implementations.

Conventions
-----------
- Functions that take raw text accept ``str | None`` and handle None.
- No imports from atlas.understanding — zero DU dependencies so this
  module can be used anywhere in the package.
"""
from __future__ import annotations

import re


# ── Normalisation ─────────────────────────────────────────────────────────────

def normalize(text: str | None) -> str:
    """Collapse whitespace and strip. Returns '' for None."""
    return " ".join((text or "").split()).strip()


def normalize_lower(text: str | None) -> str:
    return normalize(text).lower()


# ── Structural section markers ────────────────────────────────────────────────

def is_reference_heading(text: str | None) -> bool:
    """True for canonical headings that open a reference list."""
    t = normalize_lower(text)
    return t in {"references", "bibliography", "works cited", "literature cited"}


def is_abstract_heading(text: str | None) -> bool:
    t = normalize_lower(text)
    return t in {"abstract", "summary", "synopsis"}


def is_toc_heading(text: str | None) -> bool:
    """True if text is a Table of Contents heading in any supported language."""
    from atlas.understanding.core.section_labels import TOC_HEADINGS
    return normalize_lower(text) in TOC_HEADINGS


def is_appendix_heading(text: str | None) -> bool:
    t = normalize_lower(text)
    return t in {"appendix", "appendices"}


def is_keywords_heading(text: str | None) -> bool:
    t = normalize_lower(text)
    return t in {"keywords", "key words"}


# ── Caption / figure / table ──────────────────────────────────────────────────

def is_caption_like(text: str | None) -> bool:
    """True if text looks like a figure or table caption prefix."""
    t = normalize_lower(text)
    return (
        t.startswith("figure ")
        or t.startswith("fig. ")
        or t.startswith("fig ")
        or t.startswith("table ")
        or t.startswith("plate ")
        or t.startswith("image ")
        or t.startswith("photo ")
        or t.startswith("abb. ")
        or t.startswith("abbildung ")
        or t.startswith("tabelle ")
        or t.startswith("grafik ")
        or t.startswith("karte ")
        or t.startswith("tafel ")
    )


# ── Author / person lines ─────────────────────────────────────────────────────

def is_author_line(text: str | None) -> bool:
    """Heuristic: looks like a personal name, not a section heading.

    Requires at least one name-specific signal beyond title-case:
    a comma (Last, First), a conjunction between names, or a
    known name suffix/prefix. Pure title-case topic phrases like
    "Results and Discussion" are excluded.
    """
    t = normalize(text)
    if not t:
        return False
    words = t.split()
    if not 2 <= len(words) <= 8:
        return False
    if any(ch.isdigit() for ch in t):
        return False
    lower = t.lower()
    if any(tok in lower for tok in ("doi", "http", "www.", "@")):
        return False
    institution_markers = (
        "university", "universität", "institute", "institut",
        "department", "faculty", "college", "school",
        "laboratory", "centre", "center",
    )
    if any(m in lower for m in institution_markers):
        return False

    # Exclude common heading words that look title-cased
    _HEADING_WORDS = frozenset({
        "results", "discussion", "conclusion", "introduction",
        "methods", "background", "overview", "summary",
        "analysis", "approach", "framework", "model",
        "ergebnisse", "diskussion", "zusammenfassung",
        "einleitung", "methoden", "überblick",
    })
    if any(w.lower() in _HEADING_WORDS for w in words):
        return False

    titlecase_count = sum(
        1 for w in words
        if (core := w.strip(",;:()[]"))
        and core[:1].isupper()
        and (len(core) == 1 or core[1:].islower())
    )

    # Name-specific signals — these can override a relaxed titlecase check
    _NAME_SUFFIXES = ("phd", "dr.", "prof.", "md", "igb", "m.a.", "b.a.",
                      "dipl.", "mag.", "jr.", "sr.")
    has_suffix  = any(w.lower().strip(".,") in _NAME_SUFFIXES for w in words)
    has_initial = any(re.match(r'^[A-Z]\.$', w) for w in words)
    has_comma   = "," in t
    has_von     = any(w.lower() in ("von", "van", "de", "del", "della", "di")
                      for w in words)
    has_name_and = bool(re.search(
        r'\b([A-Z][a-z]+|[A-Z]\.) (and|und) ([A-Z][a-z]+|[A-Z]\.)\b', t
    ))

    strong_name_signal = any([has_suffix, has_initial, has_von, has_name_and])

    # With a strong name signal, only 1 titlecased word needed
    if strong_name_signal and titlecase_count >= 1:
        return True

    # Without strong signal, need near-complete titlecasing + comma
    if titlecase_count >= max(2, len(words) - 1) and has_comma:
        return True

    return False


def is_author_bio(text: str | None) -> bool:
    """True for biographical snippets that sometimes appear near author blocks."""
    t = normalize(text)
    if len(t.split()) < 8:
        return False
    lower = t.lower()
    bio_markers = (
        " is a ", " is an ", " retired ", " he is ", " she is ",
        " now ", " secretary ", " manager ", " mathematician ",
    )
    return any(m in lower for m in bio_markers)


# ── Contact / meta lines ──────────────────────────────────────────────────────

def is_contact_line(text: str | None) -> bool:
    """Email addresses, URLs, postal-style lines."""
    lower = normalize_lower(text)
    if not lower:
        return False
    return (
        "@" in lower
        or "http://" in lower
        or "https://" in lower
        or "www." in lower
        or lower.endswith(" uk;")
        or lower.endswith(" usa;")
    )


_RE_YEAR_INLINE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_RE_CREDIT      = re.compile(
    r"(grafik|photo|foto|image|karte|zeichnung|quelle|source|credit)[:\s]",
    re.IGNORECASE,
)


def is_meta_line(text: str | None) -> bool:
    """DOI lines, volume/issue markers, copyright notices, image credits."""
    raw = text or ""
    t = normalize_lower(text)
    if not t:
        return False
    if ("doi" in t or "©" in raw or "vol." in t
            or "openchoice" in t or "creative commons" in t):
        return True
    # Image/graphic credits: "Grafik: Name" or "Name Jahr. Grafik: ..."
    if _RE_CREDIT.search(raw):
        return True
    # "Name YYYY." pattern — editorial metadata at small font
    words = t.split()
    if (2 <= len(words) <= 8
            and _RE_YEAR_INLINE.search(raw)
            and ("." in raw or ":" in raw)):
        return True
    return False


# ── Reference entries ─────────────────────────────────────────────────────────

_RE_YEAR_PAREN = re.compile(r"\(\d{4}\)")
_RE_INITIALS   = re.compile(r"^[A-Z]\.\s+[A-Z]\.")


def is_reference_entry(text: str | None, font_size: float = 0.0,
                        italic: bool = False) -> bool:
    """True for individual bibliography entries (not the section heading itself)."""
    t = normalize(text)
    if not t:
        return False
    if is_reference_heading(t):
        return False
    if is_caption_like(t):
        return False
    lower = t.lower()
    if "@" in lower:
        return False

    score = 0
    if _RE_YEAR_PAREN.search(t):
        score += 1
    if "ed.)" in lower or "(ed." in lower:
        score += 1
    if "pp." in lower:
        score += 1
    if "isbn" in lower:
        score += 1
    if _RE_INITIALS.match(t):
        score += 1

    if font_size > 0 and font_size <= 8.5 and score >= 1:
        return True
    if italic and font_size <= 8.5 and score >= 1:
        return True
    if italic and len(t.split()) >= 8 and score >= 2:
        return True
    return False


# ── Heading quality filters ───────────────────────────────────────────────────

_RE_ARTICLE_START = re.compile(
    r"^(In|The|A|An|It|This|These|That|Those|There|We|They|He|She|"
    r"Der|Die|Das|Ein|Eine|Es|Sie|Er|Im|Für|Von|Zu|Auf)\b",
)
_BODY_CONTINUATIONS = frozenset({
    "the", "a", "an", "in", "of", "to", "with", "from",
    "at", "by", "for", "on", "as", "which", "who", "when",
})
_HEADING_IMPOSSIBLE_END = frozenset({
    "the", "a", "an", "in", "of", "to", "with", "from",
    "at", "by", "for", "on", "as", "which", "who", "when",
})


def is_fragment_heading(text: str | None, font_size: float = 0.0,
                         italic: bool = False) -> bool:
    """True for partial lines that are heading false-positives."""
    t = normalize(text)
    if not t:
        return True
    words = t.split()
    if t.endswith((")", ",", ";")):
        return True
    if italic and font_size < 10.0 and len(words) <= 2:
        return True
    if len(words) == 1:
        token = words[0].strip(".,;:()[]")
        if not token or token.islower():
            return True
        if italic and font_size <= 10.0 and token[:1].islower():
            return True
        # Single capitalised word at map/legend font size = label, not heading
        if font_size > 0 and font_size < 9.0:
            return True

    # Body continuation fragments at body font size only (< 11pt)
    if 2 <= len(words) <= 5 and (font_size == 0.0 or font_size < 11.0):
        last = words[-1].lower().strip(".,;:()")
        # Ends with a function word that cannot close a heading
        if last in _HEADING_IMPOSSIBLE_END:
            return True
        # Starts with function word AND no capitalised words follow
        first = words[0].lower().strip(".,;:()")
        if first in _BODY_CONTINUATIONS:
            caps = sum(1 for w in words[1:] if w and w[0].isupper())
            if caps == 0:
                return True
        # Article-like start + no subsequent capitals
        if _RE_ARTICLE_START.match(t):
            caps = sum(1 for w in words[1:] if w and w[0].isupper())
            if caps == 0:
                return True

    return False


def is_sentence_heading(text: str | None) -> bool:
    """True if text reads like a sentence rather than a heading title."""
    t = normalize(text)
    if not t:
        return True
    words = t.split()
    if len(words) == 1:
        return False
    if is_caption_like(t):
        return False
    if t.endswith(":") and len(words) > 5:
        return True
    if t.endswith(".") and len(words) >= 6:
        return True
    if t[:1].islower():
        return True
    alpha = sum(1 for ch in t if ch.isalpha())
    if alpha / max(len(t), 1) < 0.50:
        return True
    return False


# ── Calculation / formula labels ─────────────────────────────────────────────

_STEP_KEYWORDS_RE = re.compile(
    r'^(?:given|wanted|find|solution|approach|check|required|answer|'
    r'try|use|assume|note|notes|where|therefore|thus|'
    r'gegeben|gesucht|lösung|ansatz|ergebnis)'
    r'(?:\s*[\(\[].*?[\)\]])?\s*:',
    re.IGNORECASE,
)

_CALC_NOUN_RE = re.compile(
    r'^(?:design|section|effective|slenderness|bending|shear|volume|'
    r'critical|adjusted|deflection|camber|load|bearing|axial|moment|'
    r'stress|force|pressure|reaction|weight|floor|roof|dead|live|snow|'
    r'wind|combined|unbraced|horizontal|vertical|radial|lateral|'
    r'required|estimated|allowable|maximum|minimum|total|revised|'
    r'mid-?span|self-?weight|soffit|column|beam|connection|fastener|'
    r'reference\s+design)',
    re.IGNORECASE,
)


def is_formula_label(text: str | None) -> bool:
    """True for calculation step labels inside worked examples.

    These are short lines ending with a colon that introduce a
    calculation step, not a section heading. Two tiers:

    Tier 1 — unambiguous step keywords:
        ``Given:``, ``Solution:``, ``Wanted:``, ``Approach:``, ``Note:``, ...

    Tier 2 — structural calculation phrases (first word is an engineering
    noun) that end with a colon:
        ``Bending stress:``, ``Effective length (Table …):``,
        ``Critical buckling design value:``, ``Floor live load:``, ...

    Does NOT match lines that do not end with ``:`` — e.g.
    ``Given: A roof system …`` (body text) returns False.
    Capped at 12 words to exclude long sentence-style labels.
    """
    t = " ".join((text or "").split()).strip()
    if not t or not t.endswith(":"):
        return False
    words = t.split()
    if len(words) > 12:
        return False
    if _STEP_KEYWORDS_RE.match(t):
        return True
    if _CALC_NOUN_RE.match(t):
        return True
    return False


# ── Letter-spacing detection (Fall B — text pattern) ─────────────────────────

# Matches text where each character (or short token) is separated by a space.
# "B U R G A G E P L O T S" — at least 4 spaced tokens of 1-3 chars.
# Also handles tokens with dashes/em-dashes:
# "T H E L AW N M A R K E T – N O RT H S I D E"
# This is a PDF extraction artefact: letter-spaced text encoded as
# individual characters with spaces between them.
_LETTER_SPACED_TOKEN = r'[A-Za-z\u00C0-\u00FF]{1,3}|[–—\-]'
_LETTER_SPACED_RE = re.compile(
    r'^(?:(?:' + _LETTER_SPACED_TOKEN + r')\s+){3,}(?:' + _LETTER_SPACED_TOKEN + r')\s*$'
)


def is_letter_spaced_text(text: str | None) -> bool:
    """True if the text is letter-spaced uppercase (Fall B pattern detection).

    Detects PDF extraction artefacts where letter-spacing is encoded as
    spaces between individual uppercase characters:
        'B U R G A G E P L O T S' → True
        'Book of the Old Edinburgh Club' → False

    Fall A (char-origin measurement) is handled in typography.py / layout.py.
    This function is the surface-level fallback for cases where span data
    is unavailable or char origins are not present.
    """
    t = " ".join((text or "").split())
    if not t:
        return False
    return bool(_LETTER_SPACED_RE.match(t))


# Matches letter-spaced tokens: 1–3 uppercase chars separated by spaces,
# minimum 4 tokens. Handles double spaces between word groups.
_LETTER_SPACED_COLLAPSE_RE = re.compile(
    r'^(?:(?:[A-Za-z\u00C0-\u00FF]{1,3}|[–—\-])\s+){3,}(?:[A-Za-z\u00C0-\u00FF]{1,3}|[–—\-])\s*$'
)


def normalize_letter_spaced(text: str | None) -> str:
    """Collapse letter-spaced text to normal text, preserving capitalisation.

    PDF extraction encodes letter-spaced headings as individual characters
    separated by spaces, with double spaces between words:
        'C A S T L E  H I L L'                          → 'CASTLE HILL'
        'VA RY I N G  B U R G A G E  P L O T  W I D T H S'
                                                         → 'VARYING BURGAGE PLOT WIDTHS'

    Word boundaries are detected from:
    - Runs of 2+ spaces in the raw text
    - Newlines (multi-line letter-spaced blocks merged by block_segmentation)

    Capitalisation is preserved — no case conversion is applied.

    Returns the text whitespace-normalised but otherwise unchanged if it
    does not match the letter-spaced pattern.
    """
    raw = (text or "").strip()
    if not raw:
        return raw

    # Treat newlines as word boundaries before checking the pattern
    # Multi-line letter-spaced blocks: "T H E  PAT T E R N\nD E V E L O P M E N T"
    # becomes "T H E  PAT T E R N  D E V E L O P M E N T" (double space = boundary)
    if "\n" in raw:
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if len(lines) > 1:
            # Check if each line looks letter-spaced
            normalised_lines = [" ".join(l.split()) for l in lines]
            all_letter_spaced = all(
                _LETTER_SPACED_COLLAPSE_RE.match(nl) for nl in normalised_lines
            )
            if all_letter_spaced:
                # Join lines with double space (word boundary)
                raw = "  ".join(lines)

    normalised = " ".join(raw.split())
    if not _LETTER_SPACED_COLLAPSE_RE.match(normalised):
        return normalised
    # Split on 2+ consecutive spaces — these encode word boundaries
    word_groups = re.split(r' {2,}', raw)
    result_words = []
    for group in word_groups:
        group = group.strip()
        if not group:
            continue
        # Collapse spaces within each group (individual characters → word)
        result_words.append("".join(group.split()))
    return " ".join(result_words)


# ── Chapter / section number prefix ──────────────────────────────────────────

_CHAPTER_NUM_RE = re.compile(
    r'^(?:'
    r'\d{1,2}(?:\.\d{1,2}){0,3}'   # numeric: 1, 1.1, 1.1.1, 3.4.6
    r'|[IVX]{1,5}(?:\.\d{1,2})?'   # roman:   I, II, IV.1
    r'|[A-Z](?:\.\d{1,2})?'         # alpha:   A, A.1
    r')\s+[A-Z\u00C0-\u00FF]'       # followed by a capital letter
)

_TOC_ARTIFACT_RE = re.compile(r'\s/\s*\d+\s*$')


def contains_chapter_number(text: str | None) -> bool:
    """True if the text begins with a chapter/section number prefix.

    Matches:  '1.1 INTRODUCTION', '3.4.6 Beam Design', 'IV Results'
    Does not match TOC lines: '1.1 Introduction / 42'
    Does not match formula refs: 'Equation 3.4.3.1-2'
    """
    t = " ".join((text or "").split()).strip()
    if not t:
        return False
    if _TOC_ARTIFACT_RE.search(t):
        return False
    return bool(_CHAPTER_NUM_RE.match(t))


# ── Noise / junk ──────────────────────────────────────────────────────────────

def is_noise_text(text: str | None) -> bool:
    """True for empty, single-character, or purely numeric strings."""
    t = normalize(text)
    if not t or len(t) <= 2:
        return True
    if t.isdigit():
        return True
    return False
