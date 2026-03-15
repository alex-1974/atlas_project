# PDF Strukturerkennung: Abstände, Muster, Typografie

## Das Grundprinzip

Ein PDF kennt keine Absätze, Überschriften oder Abschnitte. Es kennt nur Zeichenblöcke mit Koordinaten. Struktur ist deshalb immer eine Interpretation — eine Kombination aus mehreren schwachen Signalen, die zusammen stark werden.

Die Kunst liegt im **Feature-Vektor**: Jede Zeile bekommt eine Menge messbarer Eigenschaften. Keine einzelne Eigenschaft ist entscheidend. Erst das Zusammenspiel ergibt die Klassifizierung.

---

## Feature-Vektor pro Zeile

Diese Merkmale sind messbar, sprachunabhängig und robust:

| Feature | Messung | Signal für |
|---|---|---|
| `font_size` | Mittlere Zeichengröße | Überschrift vs. Fließtext |
| `size_ratio` | `font_size / body_size` | Relative Hierarchie |
| `is_bold` | Anteil fetter Zeichen > 0.5 | Überschrift, Hervorhebung |
| `is_italic` | Anteil kursiver Zeichen > 0.5 | Zitat, Bildunterschrift |
| `is_all_caps` | Alle Buchstaben Großbuchstaben | Kapitelüberschrift |
| `space_before` | Abstand zur vorherigen Zeile | Abschnittsbeginn |
| `space_after` | Abstand zur nächsten Zeile | Abschnittsende |
| `space_ratio` | `space_before / median_spacing` | Relativer Abstand |
| `x_indent` | Horizontale Einrückung | Liste, Zitat, Einleitung |
| `line_width` | Textbreite relativ zur Seite | Überschrift (kurz) vs. Fließtext |
| `word_count` | Anzahl Wörter | Überschrift (< 10) vs. Text |
| `ends_with_period` | Endet mit `.` oder `:` | Fließtext vs. Überschrift |
| `starts_with_number` | `1.`, `2.1`, `§3` | Nummerierte Überschrift |
| `starts_with_bullet` | `•`, `-`, `–`, `*` | Listenpunkt |
| `page_position_y` | Relative y-Position (0–1) | Kopfzeile, Fußzeile, Titelei |
| `page_number` | Seitenzahl | Titelei (Seite 1–2) |
| `is_centered` | Mittenabweichung < Schwelle | Titel, Kapitelüberschrift |

---

## Implementierung: Feature-Extraktion

```python
import pdfplumber
import statistics
import re
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class LineFeatures:
    text:               str
    page:               int
    y_abs:              float       # Absolute y-Position (pt)
    y_rel:              float       # Relative y-Position (0.0–1.0)
    x0:                 float       # Linker Rand
    x1:                 float       # Rechter Rand
    page_width:         float

    font_size:          float = 0.0
    size_ratio:         float = 1.0  # font_size / body_size
    is_bold:            bool  = False
    is_italic:          bool  = False
    is_all_caps:        bool  = False
    is_centered:        bool  = False

    space_before:       float = 0.0
    space_after:        float = 0.0
    space_ratio:        float = 1.0  # space_before / median_spacing

    word_count:         int   = 0
    line_width_ratio:   float = 1.0  # Textbreite / Seitenbreite
    ends_with_period:   bool  = False
    starts_with_number: bool  = False
    starts_with_bullet: bool  = False

    role:               str   = "unknown"


def extract_line_features(path: str) -> list[LineFeatures]:
    """
    Extrahiert alle Zeilen mit ihrem vollständigen Feature-Vektor.
    Zwei Durchläufe: erst Rohdaten, dann relative Merkmale berechnen.
    """
    raw_lines = _collect_raw_lines(path)
    return _compute_relative_features(raw_lines)


def _collect_raw_lines(path: str) -> list[LineFeatures]:
    """Erster Durchlauf: Rohdaten aus pdfplumber."""
    lines = []

    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_height = page.height
            page_width  = page.width

            # Zeichen mit Attributen — Basis für alle Messungen
            chars = page.chars
            if not chars:
                continue

            # Zeichen nach y-Position gruppieren (Toleranz: 2pt)
            line_groups: dict[int, list] = {}
            for ch in chars:
                y_key = round(ch["top"] / 2) * 2   # auf 2pt runden
                line_groups.setdefault(y_key, []).append(ch)

            for y_key in sorted(line_groups.keys()):
                group = line_groups[y_key]
                text  = "".join(c["text"] for c in group).strip()
                if not text:
                    continue

                sizes     = [c["size"] for c in group]
                fontnames = [c.get("fontname", "") for c in group]
                x_vals    = [c["x0"] for c in group] + [c["x1"] for c in group]

                bold_count   = sum(1 for f in fontnames if "Bold" in f)
                italic_count = sum(1 for f in fontnames
                                   if "Italic" in f or "Oblique" in f)
                n = len(group)

                lf = LineFeatures(
                    text       = text,
                    page       = page_num,
                    y_abs      = y_key,
                    y_rel      = y_key / page_height,
                    x0         = min(x_vals),
                    x1         = max(x_vals),
                    page_width = page_width,
                    font_size  = statistics.mean(sizes),
                    is_bold    = (bold_count / n) > 0.5,
                    is_italic  = (italic_count / n) > 0.5,
                    is_all_caps= text.upper() == text and text.isalpha(),
                    word_count = len(text.split()),
                    ends_with_period   = text[-1] in ".;:?!" if text else False,
                    starts_with_number = bool(re.match(
                        r"^(\d+[\.\)]\s|\§\s*\d)", text)),
                    starts_with_bullet = text[0] in "•–-*▪○●" if text else False,
                )
                lines.append(lf)

    return lines


def _compute_relative_features(lines: list[LineFeatures]) -> list[LineFeatures]:
    """Zweiter Durchlauf: Abstände, Verhältnisse, Zentrierung berechnen."""
    if not lines:
        return lines

    # Körpertextgröße = Modus der gerundeten Schriftgrößen
    size_mode = statistics.mode(round(l.font_size) for l in lines)

    # Medialer Zeilenabstand (für space_ratio)
    spacings = []
    for i in range(1, len(lines)):
        if lines[i].page == lines[i-1].page:
            gap = lines[i].y_abs - lines[i-1].y_abs
            if 0 < gap < 50:   # plausible Abstände
                spacings.append(gap)
    median_spacing = statistics.median(spacings) if spacings else 12.0

    for i, line in enumerate(lines):
        # Größenverhältnis
        line.size_ratio = line.font_size / size_mode if size_mode else 1.0

        # Abstände zur Nachbarzeile (nur innerhalb derselben Seite)
        if i > 0 and lines[i-1].page == line.page:
            line.space_before = max(0, line.y_abs - lines[i-1].y_abs)
        if i < len(lines)-1 and lines[i+1].page == line.page:
            line.space_after = max(0, lines[i+1].y_abs - line.y_abs)

        line.space_ratio = line.space_before / median_spacing if median_spacing else 1.0

        # Textbreite relativ zur Seite
        line.line_width_ratio = (line.x1 - line.x0) / line.page_width

        # Zentrierung: Mittelachse der Zeile nahe Seitenmitte?
        center_line = line.page_width / 2
        text_center = (line.x0 + line.x1) / 2
        line.is_centered = abs(text_center - center_line) < (line.page_width * 0.08)

    return lines
```

---

## Klassifizierung: Scoring-Modell

Kein einzelnes Merkmal entscheidet. Jede Rolle bekommt einen Score.

```python
def classify_line(lf: LineFeatures) -> str:
    """
    Regelbasiertes Scoring: Jede mögliche Rolle erhält Punkte.
    Die Rolle mit dem höchsten Score gewinnt.
    """
    scores: dict[str, float] = {
        "header_footer":  0.0,
        "title":          0.0,
        "author":         0.0,
        "heading_1":      0.0,
        "heading_2":      0.0,
        "heading_3":      0.0,
        "body":           0.0,
        "list_item":      0.0,
        "caption":        0.0,
        "footnote":       0.0,
        "page_number":    0.0,
    }

    # ── Kopf- / Fußzeile ────────────────────────────────────────────
    if lf.y_rel < 0.08 or lf.y_rel > 0.92:
        scores["header_footer"] += 3.0
    if lf.word_count <= 5 and (lf.y_rel < 0.08 or lf.y_rel > 0.92):
        scores["header_footer"] += 2.0
    if re.match(r"^\d+$", lf.text.strip()):
        scores["page_number"] += 5.0

    # ── Titelei (Seite 1, obere Hälfte) ─────────────────────────────
    if lf.page == 1 and lf.y_rel < 0.45:
        if lf.size_ratio >= 1.8:
            scores["title"] += 5.0
        if lf.size_ratio >= 1.4 and lf.is_centered:
            scores["title"] += 3.0
        if lf.is_bold and lf.size_ratio >= 1.3:
            scores["title"] += 2.0

        # Autoren: zweite Schichtgröße unter dem Titel, oft kursiv
        if 1.0 <= lf.size_ratio < 1.4 and lf.page == 1 and lf.y_rel > 0.15:
            scores["author"] += 2.0
        if lf.is_italic and lf.page == 1:
            scores["author"] += 1.5
        if re.search(r"[A-Z]\.\s[A-Z][a-z]+|Dr\.|Prof\.", lf.text):
            scores["author"] += 3.0

    # ── Überschriften ────────────────────────────────────────────────
    short_line = lf.word_count <= 12
    no_period  = not lf.ends_with_period

    if lf.size_ratio >= 1.5 and short_line and no_period:
        scores["heading_1"] += 4.0
    if lf.size_ratio >= 1.3 and lf.is_bold and short_line:
        scores["heading_1"] += 3.0
    if lf.is_all_caps and short_line and no_period:
        scores["heading_1"] += 2.0
    if lf.space_ratio >= 2.0 and short_line:
        scores["heading_1"] += 1.5
    if lf.starts_with_number and short_line and lf.is_bold:
        scores["heading_1"] += 2.0
        scores["heading_2"] += 1.0   # könnte beides sein

    if lf.size_ratio >= 1.1 and lf.is_bold and short_line and no_period:
        scores["heading_2"] += 3.0
    if lf.space_ratio >= 1.5 and lf.is_bold and short_line:
        scores["heading_2"] += 2.0
    if lf.starts_with_number and re.match(r"^\d+\.\d+", lf.text):
        scores["heading_2"] += 3.0
        scores["heading_3"] += 1.0

    if lf.is_bold and short_line and lf.size_ratio < 1.1:
        scores["heading_3"] += 2.0
    if lf.starts_with_number and re.match(r"^\d+\.\d+\.\d+", lf.text):
        scores["heading_3"] += 4.0

    # ── Listen ───────────────────────────────────────────────────────
    if lf.starts_with_bullet:
        scores["list_item"] += 5.0
    if lf.x0 > 60 and lf.word_count <= 20 and not lf.is_bold:
        scores["list_item"] += 1.0

    # ── Bildunterschriften ───────────────────────────────────────────
    caption_pattern = r"^(Abb\.|Abbildung|Fig\.|Figure|Tab\.|Tabelle|Table)\s*\d"
    if re.match(caption_pattern, lf.text, re.IGNORECASE):
        scores["caption"] += 6.0
    if lf.is_italic and lf.size_ratio < 0.95 and lf.word_count > 3:
        scores["caption"] += 1.5

    # ── Fußnoten ─────────────────────────────────────────────────────
    if lf.size_ratio < 0.85:
        scores["footnote"] += 3.0
    if re.match(r"^\d+\s+\w", lf.text) and lf.size_ratio < 0.9:
        scores["footnote"] += 2.0

    # ── Fließtext als Auffangbecken ──────────────────────────────────
    if lf.word_count > 10 and lf.size_ratio >= 0.9:
        scores["body"] += 2.0
    if lf.ends_with_period and lf.word_count > 5:
        scores["body"] += 1.5
    if lf.line_width_ratio > 0.6:
        scores["body"] += 1.0

    # Gewinner
    return max(scores, key=scores.__getitem__)


def classify_all(lines: list[LineFeatures]) -> list[LineFeatures]:
    for line in lines:
        line.role = classify_line(line)
    return lines
```

---

## Kontextkorrektur: Nachbarn berücksichtigen

Eine Zeile allein kann täuschen. Der Kontext korrigiert.

```python
def apply_context_correction(lines: list[LineFeatures]) -> list[LineFeatures]:
    """
    Korrigiert offensichtliche Fehlklassifizierungen durch Nachbarschaft.
    
    Regeln:
    - Eine heading_1 nach drei body-Zeilen bleibt heading_1.
    - Eine body-Zeile, umgeben von heading_1 auf beiden Seiten,
      ist wahrscheinlich ein Untertitel → heading_2.
    - Fußnotenzeilen clustern am Seitenende — einzelne werden promoted.
    """
    for i in range(1, len(lines) - 1):
        prev = lines[i - 1].role
        curr = lines[i].role
        nxt  = lines[i + 1].role

        # Kurze Zeile zwischen zwei Überschriften → Untertitel
        if prev in ("heading_1", "title") and nxt in ("heading_1", "heading_2"):
            if lines[i].word_count <= 15:
                lines[i].role = "heading_2"

        # Fließtext zwischen Überschriften mit großem Abstand → neuer Abschnitt
        if (curr == "body" and
            lines[i].space_before > lines[i].space_after * 2.5 and
            lines[i].word_count <= 8):
            lines[i].role = "heading_3"

        # Einzelne Zeile nach Fußnoten-Cluster → ebenfalls Fußnote
        if prev == "footnote" and nxt == "footnote" and curr == "body":
            if lines[i].size_ratio < 0.95:
                lines[i].role = "footnote"

    return lines
```

---

## Dokumentstruktur aufbauen

```python
from dataclasses import dataclass, field

@dataclass
class Section:
    heading:  Optional[str]
    level:    int           # 0 = Dokument, 1–3 = Überschriftsebenen
    role:     str           # "title_section", "body_section", etc.
    lines:    list[str]     = field(default_factory=list)
    children: list          = field(default_factory=list)


def build_structure(lines: list[LineFeatures]) -> Section:
    """
    Baut einen hierarchischen Baum aus klassifizierten Zeilen.
    Gibt ein Section-Objekt als Wurzel zurück.
    """
    root = Section(heading=None, level=0, role="document")
    stack = [root]   # Stack repräsentiert den aktuellen Pfad

    HEADING_ROLES = {
        "title":     0,
        "heading_1": 1,
        "heading_2": 2,
        "heading_3": 3,
    }

    for line in lines:
        if line.role in HEADING_ROLES:
            level = HEADING_ROLES[line.role]
            new_section = Section(
                heading = line.text,
                level   = level,
                role    = line.role,
            )
            # Stack bis zur richtigen Tiefe leeren
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            stack[-1].children.append(new_section)
            stack.append(new_section)

        elif line.role in ("body", "list_item", "caption", "footnote"):
            stack[-1].lines.append(f"[{line.role}] {line.text}")

        # header_footer und page_number werden ignoriert

    return root


def print_structure(section: Section, depth: int = 0) -> None:
    """Gibt den Dokumentbaum lesbar aus."""
    indent = "  " * depth
    if section.heading:
        print(f"{indent}[H{section.level}] {section.heading}")
    for line in section.lines[:3]:   # Vorschau: erste 3 Zeilen
        print(f"{indent}  → {line[:80]}")
    if len(section.lines) > 3:
        print(f"{indent}  ... ({len(section.lines) - 3} weitere Zeilen)")
    for child in section.children:
        print_structure(child, depth + 1)
```

---

## Titelei erkennen: Sonderfall Seite 1

Die ersten Seiten eines Dokuments folgen anderen Regeln. Hier ein dedizierter Extraktor.

```python
def extract_front_matter(lines: list[LineFeatures]) -> dict:
    """
    Extrahiert Titelei-Elemente von Seite 1 (und ggf. Seite 2):
    Titel, Untertitel, Autoren, Affiliation, Abstract, Keywords, Datum.
    """
    front = [l for l in lines if l.page <= 2]

    result = {
        "title":       None,
        "subtitle":    None,
        "authors":     [],
        "affiliation": [],
        "abstract":    [],
        "keywords":    None,
        "date":        None,
    }

    # Titel: größte Zeile auf Seite 1
    page1 = [l for l in front if l.page == 1]
    if page1:
        largest = max(page1, key=lambda l: l.font_size)
        result["title"] = largest.text

        # Untertitel: zweitgrößte Zeile, kurz danach, kleiner
        for l in page1:
            if (l != largest and
                l.font_size < largest.font_size and
                l.font_size > statistics.mean(ll.font_size for ll in page1) and
                l.y_abs > largest.y_abs and
                l.y_abs < largest.y_abs + 80):
                result["subtitle"] = l.text
                break

    # Autoren: Muster oder role == "author"
    for l in front:
        if l.role == "author":
            result["authors"].append(l.text)
        elif re.search(
            r"[A-Z][a-z]+\s[A-Z][a-z]+|"   # Vorname Nachname
            r"[A-Z]\.\s[A-Z][a-z]+|"        # F. Nachname
            r"Dr\.|Prof\.|Univ\.",
            l.text
        ) and l.page == 1:
            result["authors"].append(l.text)

    # Abstract: Zeilen nach "Abstract"-Überschrift
    in_abstract = False
    for l in front:
        if re.match(r"^abstract$|^zusammenfassung$", l.text, re.I):
            in_abstract = True
            continue
        if in_abstract:
            if l.role in ("heading_1", "heading_2"):
                in_abstract = False
            else:
                result["abstract"].append(l.text)

    # Keywords
    for l in front:
        if re.match(r"^keywords?:|^schlüsselwörter:", l.text, re.I):
            result["keywords"] = re.sub(
                r"^keywords?:|^schlüsselwörter:", "", l.text, flags=re.I
            ).strip()

    # Datum: ISO-Datum oder ausgeschriebenes Datum
    date_pattern = (r"\b(\d{4}-\d{2}-\d{2}|"
                    r"\d{1,2}\.\s?\w+\s\d{4}|"
                    r"\w+ \d{1,2},? \d{4})\b")
    for l in front:
        m = re.search(date_pattern, l.text)
        if m:
            result["date"] = m.group(0)
            break

    return result
```

---

## Zusammenführung: Vollständige Analyse

```python
def analyze_document(path: str) -> dict:
    """Vollständige Strukturanalyse eines PDFs."""

    # Feature-Extraktion
    lines = extract_line_features(path)

    # Klassifizierung
    lines = classify_all(lines)
    lines = apply_context_correction(lines)

    # Strukturbaum
    tree = build_structure(lines)

    # Titelei
    front = extract_front_matter(lines)

    # Statistik
    role_counts = {}
    for l in lines:
        role_counts[l.role] = role_counts.get(l.role, 0) + 1

    return {
        "front_matter": front,
        "structure":    tree,
        "role_counts":  role_counts,
        "line_count":   len(lines),
    }


# Verwendung
if __name__ == "__main__":
    result = analyze_document("paper.pdf")
    print("=== Titelei ===")
    print(f"Titel:   {result['front_matter']['title']}")
    print(f"Autoren: {result['front_matter']['authors']}")
    print(f"Abstract: {' '.join(result['front_matter']['abstract'][:2])[:120]}...")
    print("\n=== Struktur ===")
    print_structure(result["structure"])
    print("\n=== Rollenverteilung ===")
    for role, count in sorted(result["role_counts"].items(),
                               key=lambda x: -x[1]):
        print(f"  {role:20s} {count:4d}")
```

---

## Kalibrierung und Debugging

Wenn die Klassifizierung fehlschlägt, liegt es fast immer an falschen Schwellenwerten. Dieser Code macht die Verteilung sichtbar:

```python
def debug_features(path: str, page_num: int = 1) -> None:
    """Gibt alle Features der ersten Seite tabellarisch aus."""
    lines = extract_line_features(path)
    page  = [l for l in lines if l.page == page_num]

    print(f"{'Text':<40} {'Size':>5} {'Ratio':>6} {'Bold':>5} "
          f"{'Ctr':>4} {'SpB':>5} {'SpR':>5} {'WC':>4}")
    print("-" * 80)
    for l in page:
        print(
            f"{l.text[:39]:<40} "
            f"{l.font_size:>5.1f} "
            f"{l.size_ratio:>6.2f} "
            f"{'Y' if l.is_bold else 'N':>5} "
            f"{'Y' if l.is_centered else 'N':>4} "
            f"{l.space_before:>5.1f} "
            f"{l.space_ratio:>5.2f} "
            f"{l.word_count:>4}"
        )
```

---

## Schwächen und Grenzen

**Mehrspaltiges Layout** bricht die y-Koordinaten-Logik. Seiten müssen zuerst in Spalten geteilt werden (`page.crop()`), dann separat analysiert werden.

**Seitenumbrüche mitten in Absätzen** erzeugen falsche `space_before`-Werte für die erste Zeile einer Seite. Lösung: Absätze über Seitengrenzen hinweg anhand von Einrückung und Satzzeichen zusammenführen.

**Gleichmäßige Schriftgrößen** (z.B. reine Fließtextdokumente ohne visuelle Hierarchie) liefern `size_ratio ≈ 1.0` überall — dann tragen nur Abstand, Fettdruck und Textmuster.

**Gescannte PDFs** liefern keine Zeichenattribute. Erst OCR, dann diese Pipeline.
