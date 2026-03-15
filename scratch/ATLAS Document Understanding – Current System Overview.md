```md
# ATLAS Document Understanding – Current System Overview
## Architektur, Datenfluss und Komponenten (Ist-Zustand)

Status: technische Dokumentation des aktuellen Systems  
Ziel: Überblick über die aktuelle Implementierung der Document-Understanding-Pipeline in ATLAS

---

# 1 Systemüberblick

ATLAS verarbeitet wissenschaftliche Dokumente (primär PDFs) und versucht daraus eine strukturierte Darstellung zu erzeugen.

Der aktuelle Fokus liegt auf:

- Extraktion von Text aus PDFs
- Zerlegung in Textblöcke
- Berechnung von Block-Signalen
- Klassifikation von Blockrollen
- Rekonstruktion der Abschnittsstruktur (Section Tree)
- einfache Dokumenttypbestimmung

Die Pipeline arbeitet primär blockbasiert und verwendet eine PostgreSQL-Datenbank zur Speicherung der Zwischenergebnisse.

---

# 2 Gesamtpipeline

Der derzeitige Ablauf lässt sich stark vereinfacht so darstellen:

```

PDF
↓
Text-Extraktion
↓
Textsegmente (Blocks)
↓
Block-Signale
↓
Rollenzuordnung
↓
Dokumenttyp-Erkennung
↓
Section Tree

```

Die einzelnen Stufen greifen auf Tabellen in der Datenbank zu und ergänzen diese.

---

# 3 CLI-Steuerung

Die Pipeline wird über die CLI gestartet.

Beispiel:

```

python -m atlas.cli du-build-map

```

Diese Funktion verarbeitet alle Dokumente und führt die Document-Understanding-Schritte aus.

Wichtige CLI-Kommandos:

```

du-build-map
inspect-du-roles
inspect-du-sections
inspect-du-document-type
inspect-du-columns

```

---

# 4 Datenbankstruktur

Die Pipeline basiert auf einer PostgreSQL-Datenbank.

Wichtige Tabellen:

## documents

Metadaten zu Dokumenten.

Typische Felder:

```

document_id
path
source

```

---

## extracted_texts

Speichert extrahierten Text.

```

document_id
page_index
text

```

---

## text_segments

Zerlegt den Text in einzelne Blöcke.

Typische Felder:

```

block_id
document_id
page_index
block_index
bbox_x0
bbox_y0
bbox_x1
bbox_y1
text

```

Diese Tabelle bildet die Grundlage für alle weiteren Analysen.

---

## du_block_signals

Speichert berechnete Signale für Textblöcke.

Beispiele:

```

font_size
is_bold
is_italic
caps_ratio
word_count
number_prefix
toc_like
reference_like

```

Diese Signale dienen als Grundlage für spätere Klassifikation.

---

## du_block_roles

Speichert die geschätzte Rolle eines Blocks.

Typische Rollen:

```

title_line
author_line
section_heading
reference_entry
body_text

```

Diese Rollen werden aus den Signals abgeleitet.

---

## du_section_tree

Speichert die rekonstruierte Abschnittsstruktur.

Typische Felder:

```

section_id
document_id
block_id
parent_section
level
title
start_block_index
end_block_index
page_start
page_end

```

---

# 5 Datenfluss

Der aktuelle Datenfluss innerhalb der Pipeline:

```

text_segments
↓
du_block_signals
↓
du_block_roles
↓
du_section_tree

```

Jeder Schritt ergänzt eine neue Tabelle.

---

# 6 Rollenklassifikation

Die Rollenklassifikation basiert auf heuristischen Scores.

Typische Kriterien:

### section_heading

- kurze Zeile
- größere Schrift
- Nummernpräfix
- kein vollständiger Satz

### reference_entry

- Jahreszahlen
- Autorennamen
- DOI
- typische Referenzmuster

### title_line

- große Schrift
- erste Seite
- kurze Zeile

### author_line

- Name-Erkennung
- Nähe zum Titel

---

# 7 Dokumenttyp-Erkennung

Die Funktion

```

infer_document_type()

```

bestimmt den Dokumenttyp anhand von Blockmustern.

Typische Typen:

```

journal_article
report
book_chapter
toc_or_index
other

```

Beispielkriterien:

TOC:

```

viele Zeilen mit Punkten oder Seitenzahlen

```

---

# 8 Section Tree Konstruktion

Die Abschnittsstruktur wird aus Überschriften rekonstruiert.

Der Ablauf:

1. Blöcke laden
2. Rollen filtern
3. Überschriften erkennen
4. Hierarchie bestimmen
5. Abschnittsspannen berechnen
6. Baum speichern

Die Hierarchie basiert derzeit hauptsächlich auf:

```

section numbering
heading roles

```

Beispiel:

```

1 Introduction
1.1 Background
1.2 Methods
2 Results

```

---

# 9 Wichtige Funktionen

## compute_section_tree()

Hauptfunktion zur Erstellung der Abschnittsstruktur.

Ablauf:

```

fetch_document_grammar_map
infer_document_type
fetch_role_blocks
build_section_tree
persist_section_tree

```

---

## build_section_tree()

Erzeugt die Hierarchie der Abschnitte.

Schritte:

1. Überschriften erkennen
2. Nummern analysieren
3. Hierarchieebenen bestimmen
4. Parent-Knoten bestimmen
5. Abschnittsspannen berechnen

---

## merge_split_headers()

Rekonstruiert Überschriften, die über mehrere Blöcke verteilt sind.

Beispiel:

```

4.2.
Holzverbindungen

```

→

```

4.2 Holzverbindungen

```

---

# 10 Dokumentanalyse-Module

Aktuelle Module innerhalb von `document_understanding`:

```

grammar/
roles/
structure/

```

### grammar

Regeln zur Dokumentstruktur.

### roles

Rollenerkennung für Blöcke.

### structure

Rekonstruktion von Abschnitten.

---

# 11 Parallelverarbeitung

Die Verarbeitung erfolgt parallel über multiprocessing.

Beispiel:

```

mp.Pool(workers)

```

Jedes Dokument wird unabhängig analysiert.

---

# 12 Debug-Tools

Zur Analyse der Pipeline existieren mehrere CLI-Kommandos.

### Rolleninspektion

```

inspect-du-roles

```

Zeigt:

```

page
block
role
score
text

```

---

### Dokumenttyp-Analyse

```

inspect-du-document-type

```

Zeigt Klassifikation der Dokumente.

---

### Abschnittsanalyse

```

inspect-du-sections

```

Zeigt den rekonstruierten Section Tree.

---

# 13 Aktuelle Grenzen

Das derzeitige System hat einige Einschränkungen.

### Layoutinformationen sind begrenzt

Derzeit fehlen detaillierte Features zu:

- Spaltenstruktur
- Schriftgrößenhierarchie
- relativen Abständen

### Rollenklassifikation ist heuristisch

Es existiert kein trainiertes Modell.

### Paragraph-Rekonstruktion fehlt

Absätze werden noch nicht explizit erkannt.

### komplexe Layouts schwierig

Probleme bei:

- mehrspaltigen Layouts
- Tabellen
- Abbildungen

---

# 14 Zusammenfassung

Der aktuelle Stand der Pipeline:

```

PDF
↓
Textsegmente
↓
Blocksignale
↓
Rollenzuordnung
↓
Dokumenttyp-Erkennung
↓
Section Tree

```

Die Architektur ist modular und lässt sich erweitern.

Die nächste Entwicklungsphase konzentriert sich auf:

- verbesserte Layoutanalyse
- relative Layoutfeatures
- Paragraph-Rekonstruktion
- robustere Dokumentstrukturmodelle
```

