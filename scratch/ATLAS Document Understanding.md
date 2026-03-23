```md
# ATLAS Document Understanding  
## Layered Structural Analysis Architecture

### Arbeitspapier – Konzept und Architektur

Version: Draft  
Status: Architekturkonzept für die nächste Ausbaustufe der ATLAS Document Understanding Pipeline

---

# 1 Ziel

Ziel der Document-Understanding-Pipeline ist es, aus **rohen PDF-Layouts** eine **semantische Dokumentstruktur** zu rekonstruieren.

Diese Struktur umfasst unter anderem:

- Titel
- Autoren
- Abstract
- Kapitel und Unterkapitel
- Absätze
- Listen
- Bild- und Tabellenbeschriftungen
- Literaturverzeichnisse
- Inhaltsverzeichnisse
- Fußnoten

Die zentrale Idee:

> Die Struktur eines Dokuments ergibt sich nicht aus einzelnen Blöcken, sondern aus **Mustern über mehrere Layer von Informationen**.

Deshalb wird ATLAS nicht als heuristischer Parser gebaut, sondern als **mehrschichtiges Analysemodell**.

---

# 2 Grundprinzip

Der Pipeline-Gedanke lautet:

```

PDF
↓
Layoutblöcke
↓
Lesereihenfolge
↓
Layout-Features
↓
Textfeatures
↓
kombinierte Evidenz
↓
Strukturhypothesen
↓
Dokumentstruktur

```

Wichtig:

Ein einzelnes Merkmal reicht nie aus.

Beispiel:

```

großer Abstand
≠ automatisch Überschrift

```

sondern:

```

größerer Abstand

* größere Schrift
* kurze Zeile
* Satzstruktur fehlt
  → Überschrift wahrscheinlich

```

---

# 3 Layer-Modell

ATLAS modelliert Dokumente in **mehreren unabhängigen Informationsschichten**.

Diese Layer können anschließend kombiniert werden.

```

reading_order
geometry
spacing
typography
text_features
reconstruction
roles
semantic_structure

```

Jeder Layer hat eine klar definierte Aufgabe.

---

# 4 Reading Order Layer

## Aufgabe

Herstellung einer **linearen Lesereihenfolge** aus dem räumlichen Layout.

PDFs enthalten oft:

- mehrere Spalten
- Floating-Elemente
- Tabellen
- Abbildungen
- unklare Textreihenfolge

Deshalb muss zuerst eine stabile Lesereihenfolge erzeugt werden.

## Eingaben

Blockinformationen:

```

page_index
bbox_x0
bbox_y0
bbox_x1
bbox_y1

```

## Schritte

1. Spaltenerkennung
2. Blockzuordnung zu Spalten
3. Sortierung innerhalb der Spalte
4. lineare Sequenzbildung

## Ergebnis

```

reading_order_index
prev_block_id
next_block_id
column_id

```

Diese Reihenfolge ist die **Basis für alle späteren Analysen**.

---

# 5 Geometry Layer

Dieser Layer beschreibt die **räumliche Struktur** des Layouts.

## Beispiele

```

block_width
block_height
bbox_x0
bbox_x1
bbox_y0
bbox_y1
column_width
relative_width

```

## Wichtige Merkmale

### relative_width

```

block_width / column_width

```

Hilft zu erkennen:

- Fließtext
- Überschrift
- Caption
- Listen
- Tabellenfragmente

---

# 6 Spacing Layer

Dieser Layer analysiert **vertikale Abstände**.

## Grundidee

Textfluss hat meist **regelmäßige Abstände**.

Abweichungen markieren Strukturgrenzen.

## Features

```

gap_before
gap_after

```

## Relative Normalisierung

Absolute Werte sind wenig aussagekräftig.

Beispiel:

```

gap_before_raw
gap_before_rel_doc
gap_before_rel_page
gap_before_rel_local

```

### gap_before_rel_doc

```

gap_before / document_gap_median

```

### gap_before_rel_local

```

gap_before / local_gap_median

```

Damit erkennt man:

- Absatzwechsel
- Kapitelwechsel
- Listen
- Captions

---

# 7 Typography Layer

Dieser Layer analysiert **Schriftmerkmale**.

## Rohdaten

```

font_size
font_family
font_weight
italic
color

```

## abgeleitete Features

```

font_size_rel_doc
font_size_rel_page
font_size_rel_local
caps_ratio
bold_ratio
italic_ratio

```

### font_size_rel_doc

```

font_size / document_font_median

```

Beispiel:

```

1.0  → Fließtext
1.4  → Überschrift
0.8  → Fußnote

```

### caps_ratio

Anteil Großbuchstaben.

Hilft bei:

```

EINLEITUNG
METHODIK
RESULTATE

```

---

# 8 Text Feature Layer

Dieser Layer analysiert den **Inhalt der Zeile**.

## Beispiele

```

word_count
sentence_like
contains_year
contains_url
contains_doi
contains_email
contains_number_prefix
contains_bullet

```

## typische Muster

### Überschrift

```

wenige Wörter
kein Satzende
keine Punktuation

```

### Referenzen

```

Jahreszahlen
Autornamen
DOI

```

### Caption

```

Figure
Table
Abb.

```

---

# 9 Rekonstruktionslayer

PDF-Blöcke entsprechen selten semantischen Einheiten.

Beispiele:

```

4.2.
Holzverbindungen

```

oder

```

1.1.
Besiedlung

```

Deshalb müssen Blöcke zusammengeführt werden.

## Beispiele

### Header Reconstruction

```

4.2.
Holzverbindungen

```

→

```

4.2 Holzverbindungen

```

### Paragraph Reconstruction

Mehrere Blöcke bilden einen Absatz.

### Caption Reconstruction

```

Figure 3.
Roof structure

```

---

# 10 Relative Feature Philosophy

Ein zentraler Grundsatz:

> Dokumentmuster erkennt man besser mit **relativen Werten**.

Absolute Werte sind abhängig von:

- Schrift
- Scanauflösung
- PDF-Generator
- Seitengröße

Beispiel:

```

font_size = 12

```

ist bedeutungslos.

Aber:

```

font_size = 1.4 × document median

```

ist sehr aussagekräftig.

---

# 11 Referenzebenen für Relationen

Relative Werte werden auf mehreren Ebenen berechnet.

## Dokumentebene

Vergleich mit gesamtem Dokument.

```

font_size_rel_doc
gap_rel_doc

```

Gut für:

- Titel
- Fußnoten
- Kapitel

---

## Seitenebene

Vergleich mit derselben Seite.

```

font_size_rel_page
gap_rel_page

```

Gut für:

- Seitenkopf
- Fußzeilen
- lokale Layoutvariationen

---

## Spaltenebene

Vergleich innerhalb der Spalte.

```

width_rel_column
indent_rel_column

```

Gut für:

- Listen
- Tabellen
- Fließtext

---

## lokale Nachbarschaft

Vergleich mit angrenzenden Blöcken.

```

font_rel_local
gap_rel_local

```

Gut für:

- Absatzgrenzen
- Überschrift-Body-Relation

---

# 12 Sequenzmuster

Dokumentstruktur entsteht nicht aus Einzelblöcken.

Sie entsteht aus **Sequenzen**.

Beispiel Paragraph:

```

Block1
Block2
Block3
Block4

```

Eigenschaften:

- gleiche Schriftgröße
- gleiche Breite
- gleiche Einrückung
- ähnliche Abstände

→ Absatz

---

# 13 Diskontinuitäten

Strukturwechsel entstehen durch **Diskontinuitäten**.

Beispiele:

```

großer Abstand
+
größere Schrift
+
kurze Zeile

```

→ Überschrift

---

# 14 Strukturhypothesen

Aus den Layern werden **Hypothesen** gebildet.

Beispiele:

```

heading_candidate
paragraph_candidate
caption_candidate
reference_candidate
toc_candidate

```

Diese Hypothesen entstehen aus kombinierter Evidenz.

---

# 15 Rollenmodell

Blockrollen werden nicht direkt bestimmt.

Stattdessen werden **Scores** berechnet.

Beispiel:

```

heading_score
paragraph_score
caption_score
reference_score

```

Die finale Rolle ergibt sich aus:

```

argmax(score)

```

---

# 16 Section Tree

Der Section Tree wird aus:

```

heading_candidates

```

gebildet.

Hierarchien entstehen aus:

```

section numbering
font hierarchy
spacing hierarchy

```

---

# 17 Beispielstruktur

```

TITLE

ABSTRACT

1 Introduction
paragraph
paragraph

2 Methods
paragraph
paragraph

3 Results
paragraph

```

---

# 18 Vorteile des Layer-Ansatzes

Der Layer-Ansatz ist:

### robust

verschiedene Layouts funktionieren.

### erklärbar

jede Entscheidung basiert auf Features.

### erweiterbar

neue Layer können ergänzt werden.

### dokumenttypunabhängig

funktioniert für:

- Papers
- Bücher
- Reports
- Dissertationen

---

# 19 Architektur im Code

Empfohlene Modulstruktur:

```

document_understanding/

reading_order/
geometry/
spacing/
typography/
text_features/
reconstruction/
roles/
structure/
semantic/

```

---

# 20 Nächste Entwicklungsschritte

1. vollständige relative Feature-Normalisierung
2. stabiler Paragraph-Reconstructor
3. bessere Caption-Erkennung
4. Literaturverzeichnis-Parser
5. robustere Section-Trees
6. Dokumenttyp-Klassifikation

---

# 21 Langfristiges Ziel

ATLAS soll Dokumente so analysieren können wie ein Mensch:

- Layout erkennen
- Struktur erkennen
- Semantik erkennen

und daraus eine **maschinenlesbare Wissensstruktur** erzeugen.

---

# Ende
```

