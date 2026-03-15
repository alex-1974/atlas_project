# PDF Understanding in Python

## Das Problem

Ein PDF ist kein Dokument — es ist ein Druckbefehl. Das Format wurde entwickelt, um Seiten pixelgenau zu reproduzieren, nicht um Inhalt maschinenlesbar zu speichern. Wer PDFs in Python "versteht", kämpft deshalb gegen die Natur des Formats selbst.

Das hat Konsequenzen: Zeilenumbrüche sind keine semantischen Grenzen. Spalten werden als Zeichenströme gespeichert. Tabellen existieren als geometrische Objekte, nicht als Datenstrukturen. Gescannte PDFs sind schlicht Bilder.

---

## Die vier Grundtypen

| Typ | Erkennungsmerkmal | Strategie |
|---|---|---|
| **Text-PDF** | Markierbarer Text im Reader | `pdfplumber`, `pypdf` |
| **Tabellen-PDF** | Sichtbare Linien, Gitternetz | `pdfplumber` mit `extract_tables()` |
| **Formular-PDF** | Ausfüllbare Felder | `pypdf` mit `fields` |
| **Gescanntes PDF** | Kein Text markierbar | OCR: `pytesseract` + `pdf2image` |

---

## Algorithmus: PDF-Typ bestimmen

```python
from pypdf import PdfReader
import pdfplumber

def classify_pdf(path: str) -> str:
    """Bestimmt den Grundtyp eines PDFs."""
    reader = PdfReader(path)

    # Schritt 1: Formularfelder prüfen
    if reader.get_fields():
        return "form"

    # Schritt 2: Textinhalt prüfen
    text = "".join(page.extract_text() or "" for page in reader.pages)
    if len(text.strip()) > 50:
        # Schritt 3: Tabellenstrukturen prüfen
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                if page.extract_tables():
                    return "table"
        return "text"

    # Kein Text → gescannt
    return "scanned"
```

---

## Algorithmus: Text extrahieren

### Einfacher Text

```python
import pdfplumber

def extract_text(path: str) -> str:
    """Extrahiert Text mit Layout-Erhalt."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                pages.append(text)
    return "\n\n".join(pages)
```

**Warum `pdfplumber` statt `pypdf`?**  
`pdfplumber` rekonstruiert den Textfluss aus Zeichenpositionen. `pypdf` liefert den rohen Zeichenstrom — oft ohne Leerzeichen zwischen Wörtern.

### Text mit Metadaten

```python
def extract_text_with_metadata(path: str) -> dict:
    """Gibt Text und Dokumentmetadaten zurück."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    meta = reader.metadata

    with pdfplumber.open(path) as pdf:
        text = "\n\n".join(
            page.extract_text() or ""
            for page in pdf.pages
        )

    return {
        "title": meta.title,
        "author": meta.author,
        "pages": len(reader.pages),
        "text": text,
    }
```

---

## Algorithmus: Tabellen extrahieren

```python
import pdfplumber
import pandas as pd

def extract_tables(path: str) -> list[pd.DataFrame]:
    """Extrahiert alle Tabellen als DataFrames."""
    results = []

    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                # Erste Zeile als Header
                df = pd.DataFrame(table[1:], columns=table[0])
                df["_source_page"] = page_num
                results.append(df)

    return results
```

**Wenn Spalten falsch erkannt werden:**

```python
# Explizite Spaltenbreiten definieren
table_settings = {
    "vertical_strategy": "lines",      # oder "text"
    "horizontal_strategy": "lines",    # oder "text"
    "snap_tolerance": 3,
    "intersection_tolerance": 3,
}

tables = page.extract_tables(table_settings)
```

---

## Algorithmus: Gescannte PDFs (OCR)

```python
import pytesseract
from pdf2image import convert_from_path
from pathlib import Path

def ocr_pdf(path: str, lang: str = "deu") -> str:
    """
    Extrahiert Text aus gescanntem PDF via OCR.
    
    Args:
        path: Pfad zum PDF
        lang: Tesseract-Sprachcode (deu, eng, fra ...)
    """
    images = convert_from_path(path, dpi=300)
    pages = []

    for i, image in enumerate(images):
        text = pytesseract.image_to_string(image, lang=lang)
        pages.append(f"[Seite {i+1}]\n{text}")

    return "\n\n".join(pages)
```

**DPI-Wahl:**
- 150 DPI: Schnell, ausreichend für Druck
- 300 DPI: Standard für gute OCR-Qualität
- 600 DPI: Nur für sehr kleine Schrift oder Handschrift

---

## Algorithmus: Vollständige Pipeline

```python
def understand_pdf(path: str) -> dict:
    """
    Universelle PDF-Verarbeitung.
    Erkennt den Typ und wendet die passende Strategie an.
    """
    pdf_type = classify_pdf(path)

    if pdf_type == "scanned":
        text = ocr_pdf(path)
        tables = []
    elif pdf_type == "table":
        text = extract_text(path)
        tables = extract_tables(path)
    elif pdf_type == "form":
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = ""
        tables = []
        fields = reader.get_fields() or {}
    else:
        text = extract_text(path)
        tables = []

    return {
        "type": pdf_type,
        "text": text,
        "tables": tables,
    }
```

---

## Best Practices

### 1. Immer mit Encoding-Fehlern rechnen

```python
text = page.extract_text() or ""   # None abfangen
text = text.encode("utf-8", errors="replace").decode("utf-8")
```

### 2. Große PDFs seitenweise verarbeiten

```python
# Nicht: gesamten Text im RAM halten
# So: Generator verwenden

def iter_pages(path: str):
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            yield page.extract_text() or ""
```

### 3. Passwortgeschützte PDFs

```python
from pypdf import PdfReader

reader = PdfReader("encrypted.pdf")
if reader.is_encrypted:
    reader.decrypt("password")
```

### 4. Bibliotheken kombinieren, nicht ersetzen

| Aufgabe | Beste Wahl |
|---|---|
| Text aus normalem PDF | `pdfplumber` |
| Tabellen | `pdfplumber` |
| Metadaten, Seiten, Formulare | `pypdf` |
| Neue PDFs erstellen | `reportlab` |
| Gescannte PDFs | `pdf2image` + `pytesseract` |
| Mergen, Splitten, Rotieren | `pypdf` oder `qpdf` (CLI) |

### 5. Fehlertoleranz einbauen

```python
def safe_extract(path: str) -> str:
    try:
        return extract_text(path)
    except Exception as e:
        # Fallback: pypdf als Backup
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )
```

---

## Installation

```bash
pip install pdfplumber pypdf reportlab pdf2image pytesseract --break-system-packages

# OCR-Engine (Ubuntu/Debian)
sudo apt-get install tesseract-ocr tesseract-ocr-deu

# Poppler für pdf2image
sudo apt-get install poppler-utils
```

---

## Häufige Fallstricke

**Mehrspaltiger Text** wird als ein Zeichenstrom ausgegeben — linke und rechte Spalte durchmischt. Lösung: `page.crop()` auf Teilbereiche anwenden.

```python
left = page.crop((0, 0, page.width / 2, page.height))
right = page.crop((page.width / 2, 0, page.width, page.height))
text = left.extract_text() + "\n" + right.extract_text()
```

**Ligaturzeichen** (ﬁ, ﬂ) werden nicht immer korrekt kodiert. Nach der Extraktion bereinigen:

```python
import unicodedata
text = unicodedata.normalize("NFKD", text)
```

**Tabellen ohne sichtbare Linien** brauchen `"vertical_strategy": "text"` — `pdfplumber` leitet Spaltengrenzen dann aus Textausrichtung ab.
