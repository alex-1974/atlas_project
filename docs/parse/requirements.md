# atlas.parse — Requirements

> Anforderungen an die parsernahe Dokumentanalyse in Atlas.

---

## Zweck

Dieses Dokument beschreibt die minimalen und erweiterten Anforderungen an `atlas.parse`.

Ziel ist es, exakt zu definieren, welche Informationen aus PDF-Dokumenten extrahiert werden müssen, um die höheren Funktionen von Atlas zu ermöglichen, ohne einen vollständigen generischen PDF-Parser zu implementieren.

Document Understanding ist kein Selbstzweck. Es dient als Grundlage für Suche, semantische Analyse, Wissensgraphen, Ranking, Zeit- und Raumdarstellungen sowie die Identifikation weiterführender Literatur.

---

## Leitprinzip

Atlas benötigt keinen universellen PDF-Parser, sondern eine zielgerichtete, wissenschaftsspezifische Dokumentanalyse.

> **So viel Struktur wie nötig – so wenig Parsing wie möglich.**

Das System extrahiert ausschließlich jene Informationen, die für die höheren Funktionen von Atlas erforderlich sind.

---

## Abgrenzung zu generischen PDF-Parsern

| Fähigkeit | atlas.parse | Generische Systeme |
|-----------|-------------|--------------------|
| Vollständige Layout-Rekonstruktion | ❌ | ✔ |
| Extraktion aller Tabellen und Grafiken | ❌ | ✔ |
| Universelle Dokumentanalyse | ❌ | ✔ |
| Wissenschaftliche Metadatenextraktion | ✔ | ✔ |
| Abschnitts- und Strukturverständnis | ✔ | ✔ |
| Referenz- und Zitationsanalyse | ✔ | ✔ |
| Wissensgraph-Integration | ❌ | ❌ |
| Semantische Suche | indirekt | ✔ |
| Deterministische Offline-Verarbeitung | ✔ | ⚠️ |

---

## Überblick über die Analyseergebnisse

| Kategorie | Beschreibung | Priorität |
|-----------|-------------|-----------|
| Bibliographische Metadaten | Titel, Autoren, Jahr | Kritisch |
| Dokumentstruktur | Section Tree, Zonen, Absätze | Kritisch |
| Identifikatoren | DOI, ISBN, ISSN, arXiv, QID | Kritisch |
| Referenzen | Literaturverzeichnis und zitierte Werke | Kritisch |
| Abstract | Kurzbeschreibung des Dokuments | Hoch |
| Dokumenttyp | Klassifikation | Hoch |
| Zeitbezug | Erscheinungsjahr | Hoch |
| Layoutinformationen | Koordinaten und Typografie | Mittel |
| Raumbezug | Orts- und Regionsbezüge | Mittel |

---

## Funktionale Anforderungen

### 1. Bibliographische Metadaten

**Ziel:** Eindeutige Identifikation und Zitierfähigkeit.

**Zu extrahierende Informationen:**
- Titel
- Autoren
- Erscheinungsjahr
- Publikationsorgan (optional)
- Abstract
- Dokumenttyp

**Verwendung in Atlas:**
- Katalogisierung
- Suche und Filterung
- Exportformate (BibTeX, JSON, CSV)
- Wissensgraph
- Ranking und Kontextualisierung

---

### 2. Dokumentstruktur

**Ziel:** Rekonstruktion der logischen Gliederung eines Dokuments.

**Zu extrahierende Informationen:**
- Überschriften
- Hierarchische Ebenen
- Section Tree
- Zonen (`front`, `body`, `back`, `references`)
- Absätze

**Verwendung in Atlas:**
- Navigation im PDF-Viewer
- Keyword-Extraktion
- Topic-Modellierung
- Kontextbasierte Analyse
- Semantische Suche

---

### 3. Absatzsegmentierung

**Ziel:** Erhaltung der semantischen Granularität.

Ein Absatz repräsentiert typischerweise eine inhaltliche Einheit. Ohne Absatzsegmentierung gehen abschnittsspezifische Themen verloren.

**Verwendung in Atlas:**
- Abschnittsbasierte Keyword-Extraktion
- Kontextbewusste Themenanalyse
- Embedding-Fallback
- Vorschauen und Snippets

---

### 4. Identifikatoren

**Ziel:** Verknüpfung mit externen Wissensquellen.

**Zu extrahierende Identifikatoren:**
- DOI
- ISBN
- ISSN
- arXiv-ID
- URN
- Wikidata-QID

**Verwendung in Atlas:**
- Metadatenanreicherung
- Eindeutige Referenzierung
- Wissensgraph
- Literaturentdeckung

---

### 5. Abstract und Textrepräsentation

**Ziel:** Semantische Repräsentation eines Dokuments.

**Priorität der Quellen:**
1. Verlässliche externe Quelle
2. Parsernahe Extraktion aus dem Dokument
3. Erster Absatz des Haupttexts als Fallback

**Verwendung in Atlas:**
- Embeddings
- Semantische Suche
- Dokumentvorschau
- Ranking

---

### 6. Referenzen

**Ziel:** Aufbau eines Zitationsnetzwerks.

**Zu extrahierende Informationen:**
- Literaturverzeichnis
- Zitierte Werke
- DOI und bibliographische Angaben

**Verwendung in Atlas:**
- Wissensgraph
- Literaturrecherche
- Ranking wissenschaftlicher Arbeiten
- Identifikation weiterführender Literatur

---

### 7. Layout- und Positionsinformationen

**Ziel:** Navigation, Visualisierung und Kontextbewusstsein.

**Zu extrahierende Informationen:**
- Bounding Boxes
- Seitenkoordinaten
- Typografie
- Seitenzahlen

**Verwendung in Atlas:**
- Sprungmarken im PDF-Viewer
- Hervorhebung von Textstellen
- Strukturvisualisierung
- Diagnostik

---

### 8. Dokumenttyp-Klassifikation

**Ziel:** Einordnung des Dokuments.

**Beispiele:**
- `journal_article`
- `archival_text`
- `report`
- `thesis`
- `book_chapter`
- `monograph`

**Verwendung in Atlas:**
- Filterung
- Ranking
- Suchkontext

---

## Scope and Limits of Document Understanding

### Zweck

Dieser Abschnitt definiert den Umfang und die Grenzen des Document Understanding in `atlas.parse`.

> **Atlas muss Dokumente nicht perfekt verstehen, sondern zuverlässig genug, um Wissen daraus zu extrahieren.**

---

### Unterstützte Dokumenttypen

| Dokumenttyp | Beispiele |
|-------------|-----------|
| Wissenschaftliche Publikationen | Journalartikel, Dissertationen |
| Fachbücher | Monografien, Sammelbände |
| Berichte | Technische und staatliche Reports |
| Archivtexte | Historische Quellen |
| Graue Literatur | White Papers, Manuals |
| Essays und Aufsätze | Fach- und populärwissenschaftliche Texte |

---

### Mindestanforderungen an das Dokumentverständnis (MVP)

| Fähigkeit | Beschreibung | Priorität |
|-----------|-------------|-----------|
| Textextraktion | Vollständige Extraktion des Dokumenttexts | Kritisch |
| Absatzsegmentierung | Identifikation semantischer Grundeinheiten | Kritisch |
| Titelbestimmung | Erkennung des Dokumenttitels | Kritisch |
| Überschriftenerkennung | Identifikation struktureller Gliederung | Kritisch |
| Abschnittsbildung | Rekonstruktion logischer Dokumentteile | Kritisch |
| Section Tree | Hierarchische Struktur des Dokuments | Hoch |
| Zonenklassifikation | Front Matter, Body und Back Matter | Hoch |
| Referenzdetektion | Identifikation von Literaturverzeichnissen | Hoch |
| Identifikatoren | DOI, ISBN, ISSN etc. | Hoch |
| Dokumenttypklassifikation | Einordnung des Dokumenttyps | Hoch |

---

### Erweiterte Fähigkeiten (Future Work)

| Fähigkeit | Nutzen |
|-----------|--------|
| Inhaltsverzeichnis-Erkennung | Verbesserte Navigation |
| Tiefere Heading-Level (L3–L4) | Feingranulare Struktur |
| Tabellen- und Abbildungserkennung | Kontextanalyse |
| Formelerkennung | Naturwissenschaftliche Dokumente |
| Fußnoten- und Marginalienanalyse | Historische Texte |
| Named Entity Recognition | Extraktion von Entitäten |
| Zeitliche und geographische Entitäten | Unterstützung von Zeitleisten und Karten |

---

### Robuste Erkennung ohne explizite Marker

| Signal | Bedeutung |
|--------|-----------|
| Schriftgröße | Erkennung von Überschriften |
| Typografie | Fett- oder Großschrift als Strukturindikator |
| Position auf der Seite | Hinweise auf Front Matter |
| Nummerierung | Hierarchische Ebenen |
| Weißraum und Abstände | Abschnittsgrenzen |
| Layoutmuster | Mehrspaltigkeit oder Einzüge |
| Lexikalische Muster | DOI, Jahreszahlen und Referenzformate |

---

### Confidence-basierter Ansatz

| Confidence Level | Bedeutung |
|------------------|-----------|
| High | Sehr zuverlässig |
| Medium | Wahrscheinlich korrekt |
| Low | Unsicher, aber plausibel |
| Unknown | Nicht bestimmbar |

---

### Grenzen der Erkennbarkeit

#### Wird zuverlässig erkannt

- Dokumenttitel und Haupttext
- Absätze und Überschriften
- Logische Abschnitte
- Referenzen und Identifikatoren
- Dokumenttyp

#### Wird nach Möglichkeit erkannt

- Inhaltsverzeichnisse
- Tiefe Heading-Hierarchien
- Tabellen und Abbildungen
- Formeln und mathematische Strukturen

#### Wird nicht von `atlas.parse` übernommen

- Katalogweite Semantik
- Ranking oder Wichtigkeitsanalyse
- Wissensgraphen über mehrere Dokumente
- Externe Metadatenanreicherung
- Annotationen und Sammlungen

---

## Reifegradmodell des Document Understanding

| Level | Fähigkeit |
|-------|-----------|
| L0 | Textextraktion |
| L1 | Absatzsegmentierung |
| L2 | Überschriftenerkennung |
| L3 | Section Tree |
| L4 | Zonenklassifikation |
| L5 | Metadaten, Identifikatoren und Referenzen |
| L6 | Erweiterte semantische Entitäten |

**Ziel für den MVP von `atlas.parse`: Level L5.**

---

## Zusammenhang mit Atlas-Funktionen

| Atlas-Funktion | Benötigte Parse-Daten |
|----------------|-----------------------|
| Volltextsuche | Textsegmente |
| Semantische Suche | Abstract, Struktur |
| Wissensgraph | Autoren, Referenzen, Identifikatoren |
| PDF-Viewer | Layout, Section Tree |
| Metadatenanreicherung | DOI, ISBN, QID |
| Keyword-Extraktion | Abschnitte und Absätze |
| Ranking | Referenzen |
| Dokumentklassifikation | Dokumenttyp |
| Export | Titel, Autoren, Jahr |
| Zeitleisten | Jahr |
| Karten / Geodaten | Ortsbezüge |
| Literaturentdeckung | Referenzen und Identifikatoren |

---

## Nicht-funktionale Anforderungen

| Anforderung | Beschreibung |
|-------------|--------------|
| Determinismus | Identische PDFs liefern identische Ergebnisse |
| Reproduzierbarkeit | Ergebnisse sind nachvollziehbar |
| Idempotenz | Mehrfache Ausführung erzeugt dieselben Resultate |
| Modularität | Parser ist unabhängig von Atlas-Core |
| Erweiterbarkeit | Neue Analyse-Layer können ergänzt werden |
| Offline-Fähigkeit | Keine externen Dienste erforderlich |
| Provenienz | Jede Information speichert ihre Quelle |
| Performance | Skalierbar für große Kataloge |
| Debugbarkeit | Logging und Diagnostik sind integriert |

---

## Datenfluss

```
PDF
│
▼
Textextraktion
│
▼
Segmentierung
│
▼
Document Understanding
│
├── Metadaten
├── Struktur
├── Identifikatoren
├── Abstract
├── Referenzen
└── Dokumenttyp
│
▼
Atlas-Kernfunktionen
├── SQLite-Katalog
├── Semantische Suche
└── Wissensgraph
```

---

## Fazit

`atlas.parse` bildet die Grundlage aller höheren Funktionen von Atlas.

Es transformiert PDFs von statischen Dateien in strukturierte Wissensobjekte.

> **Atlas versteht Dokumente nicht vollständig, sondern ausreichend.**
