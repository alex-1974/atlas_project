# atlas.parse

`atlas.parse` ist die parsernahe Dokumentanalyse-Bibliothek von Atlas.

Sie extrahiert strukturierte, dokumentinterne Informationen aus einzelnen PDFs
und stellt diese Atlas über eine stabile und klar definierte API zur Verfügung.

---

## Zweck

`atlas.parse` transformiert PDFs von statischen Dateien in strukturierte Dokumentbefunde.
Diese dienen als Grundlage für Suche, Analyse, Wissensgraphen und weitere Funktionen von Atlas.

> **`atlas.parse` ist ein Werkzeug von Atlas, nicht dessen Kern.**

---

## Leitprinzip

> So viel Struktur wie nötig – so wenig Parsing wie möglich.

`atlas.parse` extrahiert ausschließlich jene Informationen, die für die wissenschaftliche
Erschließung und Analyse von Dokumenten erforderlich sind.

---

## Zuständigkeiten

### `atlas.parse` ist verantwortlich für:

- PDF-Akquisition
- Text- und Blockextraktion
- Segmentierung
- Dokumentstruktur (Section Tree)
- Semantische Zonen (`front`, `body`, `back`, `references`)
- Metadatenextraktion (Titel, Autoren, Jahr, Abstract)
- Identifikatoren (DOI, ISBN, ISSN, arXiv, QID)
- Referenzdetektion und -analyse
- Dokumenttyp-Klassifikation
- Layout- und Positionsinformationen
- Diagnostik und Provenienz

### `atlas.parse` ist **nicht** verantwortlich für:

- Datenbankzugriffe
- Persistenz oder Migrationen
- Katalogweite Semantik
- Embeddings und semantische Suche
- Ranking wissenschaftlicher Arbeiten
- Wissensgraphen über mehrere Dokumente
- Externe Anreicherung (Wikidata, Crossref, etc.)
- Annotationen und Sammlungen
- GUI-Darstellung

Diese Aufgaben gehören zum Atlas-Core.

---

## Öffentliche API

```python
from atlas.parse import analyze_document

result = analyze_document("paper.pdf")
```

---

## ParseResult

Die Funktion liefert ein `ParseResult` mit unter anderem folgenden Informationen:

- `metadata`
- `identifiers`
- `sections`
- `text_segments`
- `references`
- `zones`
- `diagnostics`

Beispiel:

```python
result.metadata.title
result.metadata.authors
result.sections
result.references
```

---

## Logging

`atlas.parse` verwendet das Standard-Logging-Modul von Python.

- Logger-Namespace: `atlas.parse`
- Die Konfiguration erfolgt durch Atlas oder die CLI.
- `atlas.parse` konfiguriert Logging nicht selbst.

Beispiel:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

---

## Installation

Da Parser-spezifische Abhängigkeiten nicht für ganz Atlas erforderlich sind,
werden sie als optionale Extras installiert.

```bash
pip install -e .[parse]
```

Beispiel für `pyproject.toml`:

```toml
[project.optional-dependencies]
parse = [
    "pymupdf>=1.24",
    "pdfminer.six>=20231228"
]
```

---

## Projektstruktur

```text
src/atlas/parse/
├── __init__.py
├── api.py
├── pipeline.py
├── models.py
├── config.py
├── errors.py
├── logging.py
├── acquisition/
├── segmentation/
├── structure/
├── metadata/
├── identifiers/
├── references/
├── classify/
├── layout/
├── heuristics/
└── utils/
```

---

## Entwicklung

`atlas.parse` wird neu und sauber aufgebaut.

Der bisherige Code unter `src/atlas/understanding/` dient als Referenz für
Logik und Heuristiken, wird jedoch nicht direkt importiert.

---

## Nicht-funktionale Anforderungen

- Deterministisch
- Reproduzierbar
- Modular
- Erweiterbar
- Offline-fähig
- Testbar
- Debugbar durch konsistentes Logging
- Ohne direkte Datenbankabhängigkeit

---

## Dokumentation

Weitere Dokumente befinden sich unter:

- `docs/parse/architecture.md`
- `docs/parse/requirements.md`

---

## Fazit

`atlas.parse` bildet die Grundlage der Dokumentanalyse in Atlas.

> Es versteht Dokumente nicht vollständig, sondern ausreichend – genau so weit,
> wie Atlas es für wissenschaftliche Erschließung, Bewertung, Suche und Vernetzung benötigt.
