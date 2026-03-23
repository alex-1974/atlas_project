# Atlas — CLI-Struktur

> Referenzdokument für [`atlas-rebuild-roadmap.md`](./atlas-rebuild-roadmap.md)  
> Vollständige CLI-Referenz: alle Kommandos, Flags, Beispiele.

---

## Prinzip

Die CLI hat zwei strikt getrennte Bereiche:

- **Öffentliche CLI** — was ein Nutzer sieht und verwendet
- **`atlas dev`** — Entwicklung, Debugging, Testen; wird in Phase 6 entfernt

Interne Pipelineschritte (`extract-text`, `enrich-title-text`, ...) sind nicht mehr öffentlich. Sie laufen intern als Teil von `atlas add`.

---

## Öffentliche CLI

### Katalog verwalten

```bash
atlas init
# Legt .atlas/ im aktuellen Ordner an.
# Legt ~/.atlas/ an, falls noch nicht vorhanden.
# Registriert Katalog in ~/.atlas/registry.toml.

atlas add <pdf>
# Indexiert ein einzelnes Dokument vollständig.
# Intern: Extraktion → Anreicherung → Normalisierung → Segmentierung → DU → Embedding → Tripel

atlas add <ordner>
# Indexiert alle PDFs in einem Ordner.
# --resume    unterbrochenen Lauf fortsetzen

atlas update
# Erkennt neue PDFs im Katalogordner und indexiert sie nach.

atlas remove <id>
# Entfernt ein Dokument sauber aus allen Schichten:
# SQLite, LanceDB, Oxigraph.
```

### Suchen & Erkunden

```bash
atlas search "<query>"
# Volltextsuche via FTS5.
# --semantic    semantische Suche via LanceDB (Cosine-Similarity)
# --top-k N     Anzahl Ergebnisse (Standard: 10)
# --json        maschinenlesbarer Output

atlas find
# Strukturierte SQL-Abfragen.
# --author "Name"
# --year 2017-2023
# --doi "10.48550/..."
# --rvk "ST 301"
# --type journal_article|archival_text|...

atlas similar <pdf|id>
# Findet ähnliche Dokumente via Embedding-Nachbarschaft.
# --top-k N
```

### Wissensgraph

```bash
atlas refs <pdf|id>
# Zeigt das Referenznetzwerk eines Dokuments.
# --depth N     Tiefe des Netzwerks (Standard: 1)
# --json        DOT/JSON-Output

atlas graph --author "Name"
# Co-Autoren-Graph via SPARQL.
# --json / --dot

atlas concept "Begriff"
# Alle verknüpften Dokumente und Konzepte.
```

### Überblick & Diagnose

```bash
atlas status
# Kataloggröße, letzte Indexierung, Schema-Version, offene Dokumente.

atlas inspect <id>
# Einzeldokument im Detail:
# Titel, Autoren, Typ, Zonen, Section Tree.
# Basis-Output für Nutzer — nicht alle Layer.

atlas doctor
# Konsistenzprüfung:
# fehlende PDFs, Schema-Version, Modell-Cache, Oxigraph-Integrität.
```

### Anreicherung

```bash
atlas enrich <id>
# Einzeldokument anreichern.
# --crossref    DOI → Metadaten von CrossRef
# --wikidata    owl:sameAs-Verknüpfungen
# --gnd         kontrollierte Schlagwörter
# --arxiv       Metadaten via arXiv API

atlas enrich --all
# Gesamten Katalog anreichern.
# Gleiche Flags wie oben.
```

### Globale Koordination

```bash
atlas global status
# Überblick über alle Kataloge aus ~/.atlas/registry.toml.

atlas global search "<query>"
# Sequenzielle Abfrage über alle bekannten Kataloge.
# Ergebnisse mit Herkunfts-Katalog annotiert.
```

### Export

```bash
atlas export
# --bibtex      BibTeX-Datei
# --json        JSON-Dump
# --csv         CSV-Tabelle
# --output <pfad>
```

---

## `atlas dev` — Entwicklungsbereich

> Wird in Phase 6 entfernt oder in ein separates Werkzeug ausgelagert.  
> Nicht in der öffentlichen Hilfe sichtbar.

### Datenbank

```bash
atlas dev db migrate
# Alle offenen Migrationen ausführen.

atlas dev db reset
# Testdatenbank zurücksetzen (nur mit --confirm).

atlas dev schema
# Aktuelles Datenbankschema anzeigen.
```

### Basispipeline

```bash
atlas dev pipeline run <id>
# Basispipeline für ein Dokument komplett neu laufen lassen.

atlas dev pipeline step <stufe> <id>
# Einzelnen Schritt neu berechnen.
# Stufen: extract-text | extract-metadata | extract-identifiers |
#         extract-authors | enrich-titles | enrich-quality |
#         enrich-ocr | normalize | segment
```

### Document Understanding

```bash
atlas dev du process <id>
# DU-Pipeline für ein Dokument neu berechnen.
# Entspricht dem bisherigen `atlas du process`.

atlas dev du inspect <id>
# Vollständige Layer-Ansicht.
# --verbose     alle Layer-Werte pro Block
# --limit N     maximale Blockanzahl
# Entspricht dem bisherigen `atlas du inspect`.

atlas dev du process-all
# DU für alle Dokumente neu berechnen.
# --workers N   Parallelität
```

### Evaluierung

```bash
atlas dev eval <csv>
# DU-Evaluierung gegen Ground Truth CSV.
# Entspricht dem bisherigen `atlas du eval-csv`.
```

---

## Ausgabeprinzipien

- Standardmäßig: Rich-formatierter Terminal-Output
- `--json`-Flag: maschinenlesbarer Output für Scripting
- Fehler: immer mit Hinweis auf nächsten sinnvollen Schritt (`atlas doctor`, `atlas dev ...`)
- Lange Ausgaben: automatisch paginiert via `less`

---

## Konfigurationshierarchie

```
~/.atlas/config.toml        ← globale Defaults
.atlas/config.toml          ← lokale Überschreibungen
atlas search --model X      ← einmaliger CLI-Flag (höchste Priorität)
```
