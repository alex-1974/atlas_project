# PDF Semantic Understanding in Python
## Titel, Autoren, Struktur, Textart

---

## Das Problem

Metadaten in PDF-Headern sind unzuverlässig — leer, falsch oder automatisch generiert. Titel und Autoren müssen deshalb oft aus dem visuellen Layout rekonstruiert werden: großer Text oben auf Seite 1 ist wahrscheinlich der Titel. Kleingedrucktes darunter vermutlich die Autoren. Das ist Heuristik, keine Garantie.

Dasselbe gilt für Struktur: Überschriften existieren im PDF nicht als semantische Elemente, sondern als Textblöcke mit größerer Schrift, Fettdruck oder mehr Abstand. Wer Struktur erkennen will, muss typografische Signale lesen.

---

## Ebene 1: Metadaten aus dem PDF-Header

Der schnellste — und unzuverlässigste — Weg.

```python
from pypdf import PdfReader

def get_metadata(path: str) -> dict:
    reader = PdfReader(path)
    meta = reader.metadata or {}
    return {
        "title":    meta.get("/Title", "").strip(),
        "author":   meta.get("/Author", "").strip(),
        "subject":  meta.get("/Subject", "").strip(),
        "creator":  meta.get("/Creator", "").strip(),   # Programm, das das PDF erzeugte
        "producer": meta.get("/Producer", "").strip(),  # PDF-Konverter
        "pages":    len(reader.pages),
    }
```

**Wann Metadaten brauchbar sind:** Akademische Verlage (Springer, Elsevier, PubMed) pflegen sie meist korrekt. Word-Export und LaTeX ebenfalls, wenn der Autor sie gesetzt hat.

**Wann sie fehlen oder lügen:** Scan-to-PDF, Druckertreiber-Exports, ältere Dokumente.

---

## Ebene 2: Titel und Autoren aus dem Layout

Wenn der Header leer ist, liest man die erste Seite visuell.

```python
import pdfplumber

def extract_title_author_heuristic(path: str) -> dict:
    """
    Heuristik: Titel = größter Text auf Seite 1.
    Autoren = zweitgrößter Block oder Zeile unter dem Titel.
    """
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(extra_attrs=["size", "fontname"])

    if not words:
        return {"title": None, "authors": None}

    # Schriftgrößen inventarisieren
    sizes = sorted(set(w["size"] for w in words), reverse=True)
    largest = sizes[0]
    second  = sizes[1] if len(sizes) > 1 else largest

    # Titel: alle Wörter mit maximaler Schriftgröße
    title_words = [w["text"] for w in words if abs(w["size"] - largest) < 0.5]
    title = " ".join(title_words)

    # Autoren: alle Wörter mit zweitgrößter Schrift
    author_words = [w["text"] for w in words if abs(w["size"] - second) < 0.5]
    authors = " ".join(author_words) if author_words != title_words else None

    return {
        "title":   title or None,
        "authors": authors,
    }
```

**Grenzen:** Funktioniert gut bei wissenschaftlichen Artikeln und Berichten. Versagt bei mehrspaltigem Layout, wenn Bildunterschriften die größte Schrift tragen, oder bei Titelseiten mit Logos.

---

## Ebene 3: Textstruktur erkennen

Struktur = Hierarchie aus Überschriften, Fließtext, Listen, Fußnoten, Bildunterschriften.

### Schritt 1: Zeichenattribute extrahieren

```python
def extract_char_attributes(path: str) -> list[dict]:
    """Gibt alle Textblöcke mit Schriftgröße, Fettdruck und Position zurück."""
    blocks = []
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            for char in page.chars:
                blocks.append({
                    "text":      char["text"],
                    "size":      round(char["size"], 1),
                    "bold":      "Bold" in char.get("fontname", ""),
                    "italic":    "Italic" in char.get("fontname", "") or
                                 "Oblique" in char.get("fontname", ""),
                    "x0":        char["x0"],
                    "top":       char["top"],
                    "page":      page_num,
                })
    return blocks
```

### Schritt 2: Zeilen rekonstruieren und klassifizieren

```python
import statistics

def classify_lines(path: str) -> list[dict]:
    """
    Klassifiziert jede Zeile als: title, heading, subheading,
    body, caption, footnote, header_footer.
    """
    with pdfplumber.open(path) as pdf:
        all_lines = []
        for page_num, page in enumerate(pdf.pages, 1):
            words = page.extract_words(extra_attrs=["size", "fontname"])
            # Wörter nach vertikaler Position gruppieren (= Zeilen)
            lines = {}
            for w in words:
                y = round(w["top"])
                lines.setdefault(y, []).append(w)

            for y, line_words in sorted(lines.items()):
                text  = " ".join(w["text"] for w in line_words)
                sizes = [w["size"] for w in line_words]
                bolds = ["Bold" in w.get("fontname","") for w in line_words]
                all_lines.append({
                    "text":    text,
                    "size":    statistics.mean(sizes),
                    "bold":    any(bolds),
                    "y":       y,
                    "page":    page_num,
                    "x0":      min(w["x0"] for w in line_words),
                })

    # Basistextgröße bestimmen (Modus)
    all_sizes = [l["size"] for l in all_lines]
    body_size = statistics.mode([round(s) for s in all_sizes])

    # Klassifizierung
    classified = []
    for line in all_lines:
        s = line["size"]
        role = _assign_role(line, s, body_size)
        classified.append({**line, "role": role})

    return classified


def _assign_role(line: dict, size: float, body_size: float) -> str:
    text = line["text"].strip()
    y    = line["y"]
    page = line["page"]

    # Kopf-/Fußzeile: sehr oben oder sehr unten, kurzer Text
    if (y < 50 or y > 750) and len(text) < 80:
        return "header_footer"

    # Fußnote: kleine Schrift, oft mit Ziffer beginnend
    if size < body_size - 2:
        return "footnote"

    # Bildunterschrift: kleine Schrift, beginnt mit "Abb.", "Fig.", "Tab."
    if size <= body_size and text[:4] in ("Abb.", "Fig.", "Tab.", "Tabl"):
        return "caption"

    # Überschrift Ebene 1: deutlich größer als Fließtext
    if size >= body_size + 4 or (size >= body_size + 2 and line["bold"]):
        return "heading_1"

    # Überschrift Ebene 2: etwas größer oder fett
    if size >= body_size + 1.5 or (size > body_size and line["bold"]):
        return "heading_2"

    # Fließtext
    return "body"
```

### Schritt 3: Dokumentbaum aufbauen

```python
def build_document_tree(classified_lines: list[dict]) -> list[dict]:
    """
    Wandelt flache Zeilenliste in hierarchischen Baum:
    [{heading, level, content: [lines]}, ...]
    """
    sections = []
    current = {"heading": None, "level": 0, "content": []}

    for line in classified_lines:
        role = line["role"]
        if role == "heading_1":
            if current["content"]:
                sections.append(current)
            current = {"heading": line["text"], "level": 1, "content": []}
        elif role == "heading_2":
            if current["content"]:
                sections.append(current)
            current = {"heading": line["text"], "level": 2, "content": []}
        elif role == "body":
            current["content"].append(line["text"])

    if current["content"]:
        sections.append(current)

    return sections
```

---

## Ebene 4: Textart klassifizieren

Ist das Dokument ein wissenschaftlicher Artikel, ein Bericht, ein Vertrag, eine Präsentation?

### Regelbasiert (schnell, transparent)

```python
import re

def classify_document_type(text: str, sections: list[dict]) -> str:
    """
    Klassifiziert das Dokument anhand von Textmerkmalen.
    Gibt einen von sieben Typen zurück.
    """
    text_lower = text.lower()
    headings   = [s["heading"] or "" for s in sections if s["heading"]]
    h_text     = " ".join(headings).lower()

    # Wissenschaftlicher Artikel
    academic_signals = ["abstract", "introduction", "methods", "results",
                        "discussion", "conclusion", "references", "doi",
                        "abstract:", "keywords:"]
    if sum(1 for s in academic_signals if s in text_lower) >= 3:
        return "academic_paper"

    # Rechtsdokument / Vertrag
    legal_signals = ["whereas", "hereinafter", "pursuant", "article", "§",
                     "clause", "parties", "obligations", "jurisdiction"]
    if sum(1 for s in legal_signals if s in text_lower) >= 3:
        return "legal_document"

    # Technischer Bericht / Handbuch
    tech_signals = ["specification", "requirement", "installation",
                    "configuration", "figure", "table", "appendix"]
    if sum(1 for s in tech_signals if s in text_lower) >= 3:
        return "technical_report"

    # Präsentation (wenig Text, viele Seiten mit kurzem Inhalt)
    avg_words_per_section = (
        sum(len(" ".join(s["content"]).split()) for s in sections) /
        max(len(sections), 1)
    )
    if avg_words_per_section < 40:
        return "presentation"

    # Geschäftsbericht / Finanzdokument
    financial_signals = ["revenue", "profit", "loss", "fiscal", "quarter",
                         "earnings", "balance sheet", "cash flow"]
    if sum(1 for s in financial_signals if s in text_lower) >= 3:
        return "financial_report"

    # Nachrichtenartikel / Magazin
    if re.search(r"\b(january|february|march|april|may|june|july|august|"
                 r"september|october|november|december)\b", text_lower):
        if len(sections) <= 5:
            return "news_article"

    return "general_document"
```

### KI-gestützt (robuster, sprachunabhängig)

Für komplexe Fälle — mehrsprachige Dokumente, unstrukturierte Layouts — ist ein LLM die bessere Wahl.

```python
import anthropic

def classify_with_llm(text: str, max_chars: int = 3000) -> dict:
    """
    Nutzt Claude zur Klassifizierung. Sendet nur den Anfang des Dokuments.
    """
    client = anthropic.Anthropic()
    excerpt = text[:max_chars]

    prompt = f"""Analysiere diesen Textauszug aus einem PDF-Dokument.

Antworte ausschließlich als JSON-Objekt mit diesen Feldern:
- "type": einer von [academic_paper, legal_document, technical_report,
           financial_report, news_article, presentation, book_chapter,
           government_document, general_document]
- "language": ISO-639-1-Code (de, en, fr ...)
- "title": erkannter Titel oder null
- "authors": erkannte Autoren als Liste oder null
- "confidence": Zuverlässigkeit der Klassifizierung (0.0–1.0)
- "reasoning": Ein Satz Begründung

Textauszug:
---
{excerpt}
---"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    raw = message.content[0].text
    # JSON aus möglichem Markdown-Fence extrahieren
    raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
    return json.loads(raw)
```

---

## Vollständige Pipeline

```python
def full_document_understanding(path: str) -> dict:
    """
    Führt alle Erkennungsebenen aus und gibt ein
    strukturiertes Dokumentobjekt zurück.
    """
    # 1. Metadaten
    meta = get_metadata(path)

    # 2. Text extrahieren
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        full_text = "\n\n".join(
            page.extract_text() or "" for page in pdf.pages
        )

    # 3. Layout-basierte Titel/Autoren-Erkennung (Fallback)
    if not meta["title"]:
        layout_meta = extract_title_author_heuristic(path)
        meta["title"]  = layout_meta["title"]
        meta["authors_heuristic"] = layout_meta["authors"]

    # 4. Struktur erkennen
    lines    = classify_lines(path)
    sections = build_document_tree(lines)

    # 5. Dokumenttyp bestimmen
    doc_type = classify_document_type(full_text, sections)

    return {
        "metadata":  meta,
        "type":      doc_type,
        "sections":  sections,
        "full_text": full_text,
    }
```

---

## Entscheidungsbaum: Welche Methode wann?

```
PDF einlesen
    │
    ├── Metadaten vollständig? ──→ Direkt verwenden
    │
    ├── Metadaten fehlen?
    │       └──→ Layout-Heuristik (Seite 1, Schriftgröße)
    │
    ├── Strukturerkennung nötig?
    │       ├── Einfaches Dokument ──→ Regelbasiert (classify_lines)
    │       └── Komplexes Layout  ──→ pdfplumber.chars + Clustering
    │
    └── Textart-Klassifizierung
            ├── Bekannte Sprache, strukturierter Text ──→ Regelbasiert
            └── Mehrsprachig / unbekanntes Format    ──→ LLM (Claude)
```

---

## Grenzen und Fehlerquellen

**Schriftgrößen-Heuristik versagt bei:** Dokumenten, in denen Lauftext variiert (Zeitschriftenlayout), oder wenn Überschriften dieselbe Größe wie Fließtext haben, aber anders positioniert sind.

**Regelbasierte Typklassifizierung versagt bei:** Nicht-englischen Dokumenten (Signalwörter fehlen), Hybrid-Dokumenten (Gutachten mit rechtlichen und technischen Abschnitten), kurzen Fragmenten.

**LLM-Klassifizierung ist ungeeignet für:** Sehr lange Dokumente ohne klaren Anfang, Dokumente mit vertraulichem Inhalt (der Auszug verlässt den lokalen Rechner).

---

## Installation

```bash
pip install pdfplumber pypdf anthropic --break-system-packages
```
