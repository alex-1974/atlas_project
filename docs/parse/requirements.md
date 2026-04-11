# atlas.parse — Requirements

> Anforderungen an die parsernahe Dokumentanalyse in Atlas.

---

## Zweck

Dieses Dokument beschreibt die minimalen und erweiterten Anforderungen an `atlas.parse`.

Ziel ist es, exakt zu definieren, welche Informationen aus PDF-Dokumenten extrahiert werden müssen,
um die höheren Funktionen von Atlas zu ermöglichen, ohne einen vollständigen generischen PDF-Parser zu implementieren.

---

## Leitprinzip

Atlas benötigt keinen universellen PDF-Parser, sondern eine zielgerichtete, wissenschaftsspezifische Dokumentanalyse.

> So viel Struktur wie nötig – so wenig Parsing wie möglich.

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

Zu extrahierende Informationen:
- Titel
- Autoren
- Erscheinungsjahr
- Abstract
- Dokumenttyp

---

### 2. Dokumentstruktur

**Ziel:** Rekonstruktion der logischen Gliederung eines Dokuments.

Zu extrahierende Informationen:
- Überschriften
- Hierarchische Ebenen
- Section Tree
- Zonen (`front`, `body`, `back`, `references`)
- Absätze

---

### 3. Identifikatoren

Zu extrahierende Identifikatoren:
- DOI
- ISBN
- ISSN
- arXiv-ID
- URN
- Wikidata-QID

---

### 4. Referenzen

**Ziel:** Aufbau eines Zitationsnetzwerks.

Zu extrahierende Informationen:
- Literaturverzeichnis
- Zitierte Werke
- Bibliographische Angaben

---

### 5. Layout- und Positionsinformationen

Zu extrahierende Informationen:
- Bounding Boxes
- Seitenkoordinaten
- Typografie
- Seitenzahlen

---

### 6. Dokumenttyp-Klassifikation

Beispiele:
- `journal_article`
- `archival_text`
- `report`
- `thesis`
- `book_chapter`

---

## Zusammenhang mit Atlas-Funktionen

| Atlas-Funktion | Benötigte Parse-Daten |
|----------------|-----------------------|
| Volltextsuche | Textsegmente |
| Semantische Suche | Abstract, Struktur |
| Wissensgraph | Autoren, Referenzen, Identifikatoren |
| PDF-Viewer | Layout, Section Tree |
| Ranking | Referenzen |
| Export | Titel, Autoren, Jahr |
| Zeitleisten | Jahr |
| Karten | Ortsbezüge |

---

## Minimale Ausgabe (MVP)

| Kategorie | Erforderlich |
|-----------|-------------|
| Titel | ✔ |
| Autoren | ✔ |
| Abstract | ✔ |
| DOI | ✔ |
| Section Tree | ✔ |
| Zonen | ✔ |
| Referenzen | ✔ |
| Absatzsegmente | ✔ |
| Dokumenttyp | ✔ |

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
| Debugbarkeit | Logging und Diagnostik sind integriert |
| Performance | Skalierbar für große Kataloge |

---

## Fazit

`atlas.parse` bildet die Grundlage der Dokumentanalyse in Atlas.

> `atlas.parse` versteht Dokumente nicht vollständig, sondern ausreichend –  
> genau so weit, wie Atlas es für wissenschaftliche Erschließung, Bewertung,
> Suche und Vernetzung benötigt.
