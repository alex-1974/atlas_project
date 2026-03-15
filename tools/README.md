# Atlas Helper Tools

Diese kleinen Hilfstools sind für **statische Projektanalyse** gedacht.
Sie helfen dabei, drei Dinge schneller zu verstehen:

1. **Programmstruktur**
2. **Pipeline / Flow**
3. **Datenbankaufbau**

Die Tools arbeiten ohne tiefe Integration in Atlas und lesen vor allem:

- `src/atlas/**/*.py`
- `migrations/*.sql`
- optional `README.md`

Damit sind sie robust genug für Exploration, Audits und Onboarding,
auch wenn sich intern noch etwas umbaut.

---

## Enthaltene Tools

### 1. `call_graph.py`

Erzeugt eine **statische Call- und Modulgraph-Sicht** aus Python-Dateien.

Was es liefert:

- Modul-Importgraph
- Funktionsdefinitionen pro Datei
- lokale Funktionsaufrufe
- Ausgabe als Markdown oder Mermaid

Nützlich für:

- Architekturüberblick
- Erkennen zentraler Orchestratoren
- Auffinden enger Kopplung
- Überblick über DU-Pipeline-Module

---

### 2. `db_schema_report.py`

Liest SQL-Migrationsdateien und erzeugt einen **DB-Report**.

Was es erkennt:

- `create table`
- Spalten und Typen
- Primärschlüssel-Hinweise
- `references ...`
- einfache Indexe
- `alter table ... add column`

Nützlich für:

- DB-Onboarding
- Tabellen/Felder auf einen Blick
- Schema-Diff über Migrationsstände
- Vorbereitung für spätere ER-Dokumentation

---

### 3. `pipeline_map.py`

Erzeugt eine **Flow-Sicht** auf Atlas.

Quellen:

- optional `src/atlas/cli.py`
- optional `README.md`
- optionale Fallback-Pipeline

Was es liefert:

- Pipeline-Schritte in Reihenfolge
- CLI-Command-Liste
- Mermaid-Flowchart
- Markdown-Zusammenfassung

Nützlich für:

- neues Teammitglied schnell onboarden
- Reihenfolge der Jobs verstehen
- ETL/DU-Pipeline sauber dokumentieren

---

### 4. `project_inventory.py`

Erzeugt ein **Projektinventar**.

Was es liefert:

- Package-/Modulbaum
- Python-Dateien mit Kurzstatistik
- Klassen/Funktionen pro Modul
- grobe Hotspots nach Umfang

Nützlich für:

- Überblick über Codebasis
- Auffinden großer / zentraler Module
- Vorbereitung für Refactoring

---

## Beispielaufrufe

Aus dem Projekt-Root:

```bash
python tools/dev/call_graph.py --root . --package src/atlas --format mermaid > var/reports/call_graph.md
python tools/dev/db_schema_report.py --migrations migrations > var/reports/db_schema.md
python tools/dev/pipeline_map.py --root . > var/reports/pipeline.md
python tools/dev/project_inventory.py --package src/atlas > var/reports/project_inventory.md
```

---

## Empfohlener Zielordner im Projekt

```text
tools/dev/
```

und Reports nach:

```text
var/reports/
```

---

## Praktischer Nutzen für Atlas

Atlas hat laut README eine deterministische Pipeline von
`discover → register → extract-text → ... → search`.
Dafür sind Flow- und CLI-Hilfen besonders wertvoll. fileciteturn0file0

Die Roadmap zeigt außerdem, dass Atlas sich von klassischem Text Mining
in Richtung **Document Understanding** bewegt. Gerade dabei werden
Call-Graph, Flow-Map und DB-Schema-Reports wichtig, weil neue DU-Module,
Regionstabellen und Extraktionspfade dazukommen. fileciteturn0file1 fileciteturn0file2

---

## Grenzen

- Der Call Graph ist **statisch** und erkennt keine dynamischen Dispatches vollständig.
- SQL-Parsing ist absichtlich heuristisch und kein vollständiger SQL-Parser.
- CLI-Erkennung ist generisch; je nach Framework kann Nachschärfung nötig sein.

Trotzdem sind die Tools sehr brauchbar für Architekturarbeit, Audits,
Handouts und Umbauphasen.
