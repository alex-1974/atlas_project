# atlas.parse — Architecture

> Interne Architektur von `atlas.parse` als parsernahes Subpackage innerhalb von Atlas.

---

## Zweck

`atlas.parse` ist die parsernahe Dokumentanalyse-Bibliothek von Atlas.

Sie extrahiert aus einem einzelnen PDF strukturierte, dokumentinterne Informationen
und stellt diese Atlas über eine kleine, stabile API zur Verfügung.

`atlas.parse` ist ein Werkzeug von Atlas, nicht dessen Kern.

---

## Leitprinzip

> `atlas.parse` rekonstruiert nicht das gesamte PDF, sondern genau jene Strukturen,
> die für wissenschaftliche Erschließung, Suche, Bewertung und Vernetzung erforderlich sind.

---

## Architektonische Rolle

`atlas.parse` sitzt zwischen Rohdokument und Atlas-Core.

PDF → atlas.parse → Atlas-Core

---

## Verantwortung von `atlas.parse`

`atlas.parse` ist zuständig für parsernahe, dokumentinterne Analyse eines einzelnen Dokuments.

### Dazu gehören:

- PDF-Akquisition
- Text- und Blockextraktion
- Segmentierung
- parsernahe Layoutmerkmale
- Dokumentstruktur
- dokumentinterne Rollen und Zonen
- Titel-, Autoren-, Abstract- und Jahr-Extraktion
- Identifikatoren
- Referenzdetektion und Referenzzerlegung
- Dokumenttyp-Klassifikation
- Diagnostik / Provenienz auf Parse-Ebene

---

## Was **nicht** zu `atlas.parse` gehört

Folgende Aufgaben bleiben ausdrücklich außerhalb von `atlas.parse`:

- Datenbankzugriffe
- Migrationen
- Persistenz von Parse-Ergebnissen
- katalogweite Topic-Logik
- Embeddings
- semantische Suche auf Katalogebene
- Ranking / Wichtigkeitsanalyse
- Wissensgraph über mehrere Dokumente
- externe Anreicherung (Wikidata, Crossref, GND, RVK, ...)
- Sammlungen
- Annotationen
- Nutzerlogik
- GUI-spezifische Darstellung

---

## Designregel

> Alles, was aus einem einzelnen Dokument isoliert bestimmt werden kann, darf in `atlas.parse` leben.  
> Alles, was Vergleich, Katalogkontext oder Nutzerkontext braucht, gehört nicht hinein.

---

## Öffentliche API

```python
from atlas.parse import analyze_document

result = analyze_document("paper.pdf")
```

---

## Modulstruktur

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

## ParseResult statt DB-Zugriff

`atlas.parse` schreibt nicht direkt in die Datenbank.

**Grundsatz:**  
Parser extrahiert. Atlas persistiert.

---

## Logging

`atlas.parse` verwendet das Standard-Logging-Modul von Python.

### Logger-Namespace

```
atlas.parse
```

### Regeln

- `atlas.parse` konfiguriert Logging nicht selbst
- die Konfiguration erfolgt durch Atlas oder die CLI
- strukturierte Diagnostik wird zusätzlich in `ParseResult.diagnostics` abgelegt

---

## Optionale Abhängigkeiten

Parser-spezifische Abhängigkeiten werden als optionale Extras konfiguriert:

```toml
[project.optional-dependencies]
parse = [
  "pymupdf>=1.24",
  "pdfminer.six>=20231228",
]
```

Installation:

```bash
pip install -e .[parse]
```

---

## Fazit

`atlas.parse` ist die parsernahe Analysebibliothek innerhalb von Atlas.

> `atlas.parse` extrahiert dokumentinterne Struktur und funktionale Semantik.  
> Atlas speichert, verknüpft und interpretiert diese Ergebnisse im größeren Wissenskontext.
