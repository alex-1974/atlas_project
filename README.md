# Atlas

Atlas ist ein lokales Werkzeug zur Verwaltung, Erschließung und Erkundung
wissenschaftlicher und historischer PDF-Sammlungen. Es läuft vollständig
offline, braucht keinen Server und keine Cloud-Dienste.

---

## Wozu Atlas?

Wer größere Mengen an PDFs sammelt – wissenschaftliche Aufsätze, historische
Archivdokumente, Berichte, Bücher – steht vor einem strukturellen Problem:
Die Dokumente sind vorhanden, aber nicht erschlossen. Titel und Autoren
stehen irgendwo im PDF, aber nicht zuverlässig in Metadaten. Querverweise
zwischen Dokumenten existieren als Fließtext, aber nicht als maschinenlesbare
Beziehungen. Volltextsuche findet Wörter, aber nicht Konzepte.

Atlas löst dieses Problem lokal, ohne externe Dienste, ohne Datenweitergabe.

---

## Was Atlas tut

Ein Dokument durchläuft beim Hinzufügen zur Sammlung eine vollständige
Verarbeitungskette:

**Extraktion** – Text, Metadaten, Identifier (DOI, arXiv, ISBN) werden
aus dem PDF gelesen.

**Document Understanding** – Das Dokument wird geometrisch und typografisch
analysiert. Jeder Textblock bekommt eine semantische Rolle (Titel, Autor,
Überschrift, Fließtext, Referenz, ...). Kapitelstruktur, Zonen und
Dokumenttyp werden erkannt.

**Indexierung** – Drei Indexschichten werden befüllt:
SQLite für strukturierte Abfragen und Volltextsuche,
Oxigraph für Beziehungen im Wissensgraph,
LanceDB für semantische Ähnlichkeitssuche.

**Erschließung** – Keywords, Topic und bibliografische Klassifikation
werden lokal (YAKE) oder über externe Quellen (GND, RVK, Wikidata,
CrossRef) angereichert. Alles optional, alles explizit.

---

## Schnellstart

```bash
# Katalog anlegen
cd ~/meine-literatur
atlas init

# PDFs indexieren
atlas add paper.pdf
atlas add ./ordner/ --resume

# Suchen
atlas search "Hallenhaus Westfalen"
atlas find --type article --year 2020-2024
atlas similar 48feef86              # semantisch ähnliche Dokumente

# Erschließen (braucht Netz)
atlas enrich --keywords             # YAKE lokal
atlas enrich --gnd --topic          # GND + Topic über lobid.org
atlas enrich --rvk                  # RVK-Klassifikation

# Erkunden
atlas inspect 48feef86              # Einzeldokument detail
atlas refs 48feef86                 # Referenznetzwerk
atlas graph --author "Robin Tait"   # Co-Autoren
atlas concept "Fachwerkbau"         # Konzept-Suche
```

---

## Kernkonzepte

### Katalog

Der Katalog ist eine lokale Sammlung von PDFs in einem Ordner.
Er wird durch `atlas init` initialisiert und speichert alle Daten
im Unterordner `.atlas/`. Ein Nutzer kann mehrere unabhängige Kataloge
führen (z.B. einen für Fachliteratur, einen für Archivmaterial).
Eine globale Registry in `~/.atlas/` verwaltet alle bekannten Kataloge.

### Dokument-Lebenszyklus

```
atlas add <pdf>
    → Extraktion → DU → Keywords → Indexierung (SQLite + LanceDB + Oxigraph)

atlas update
    → erkennt neue PDFs im Katalogordner, verarbeitet sie nach

atlas remove <id>
    → entfernt das Dokument sauber aus allen Indexschichten

atlas enrich <id>
    → reichert mit externen Quellen an (GND, RVK, Wikidata, CrossRef)
```

### Drei Indexschichten

Atlas nutzt drei komplementäre Speichersysteme, die gemeinsam mehr
leisten als jedes einzeln:

| Schicht | Technologie | Fragetyp |
|---|---|---|
| Strukturiert | SQLite + FTS5 | „Alle Aufsätze von Autor X aus 2018–2022" |
| Relational | Oxigraph (RDF) | „Welche Dokumente zitiert dieses Paper?" |
| Semantisch | LanceDB | „Welche Dokumente behandeln ähnliche Themen?" |

### Document Understanding

Atlas versteht nicht nur den Text eines Dokuments, sondern seine Struktur.
Die DU-Pipeline analysiert jeden Block geometrisch (Position, Größe, Abstände),
typografisch (Schriftart, Größe, Fettdruck) und semantisch (was bedeutet
dieser Block im Dokumentkontext?). Das Ergebnis ist ein strukturiertes
Modell des Dokuments mit Kapitelbaum, Zonen (Titelei, Body, Backmatter)
und semantischen Rollen pro Block.

→ Details: [`ARCHITECTURE-DU-PIPELINE.md`](./ARCHITECTURE-DU-PIPELINE.md)

### Wissensgraph

Beziehungen zwischen Dokumenten – Zitationen, gemeinsame Autoren,
verwandte Konzepte – werden als RDF-Tripel in Oxigraph gespeichert
und über SPARQL abfragbar gemacht. Der Graph wächst mit der Sammlung.

→ Details: [`ARCHITECTURE-KNOWLEDGE-GRAPH.md`](./ARCHITECTURE-KNOWLEDGE-GRAPH.md)

### Erschließung

Atlas trennt zwischen automatischer Basiserschließung (`atlas add`)
und expliziter Anreicherung (`atlas enrich`):

| Zeitpunkt | Was | Kommando |
|---|---|---|
| `atlas add` | Keywords via YAKE (lokal, kein Netz) | automatisch |
| `atlas enrich` | GND-Entitäten (lobid.org) | `--gnd` |
| `atlas enrich` | Topic (GND-normalisiert) | `--topic` |
| `atlas enrich` | Section-Keywords pro Kapitel | `--section-keywords` |
| `atlas enrich` | RVK-Klassifikation | `--rvk` |
| `atlas enrich` | Wikidata QID + ORCID | `--wikidata` |
| `atlas enrich` | Vollständige Metadaten via DOI | `--crossref` |

---

## Unterstützte Dokumenttypen

- Wissenschaftliche Aufsätze (Journal Articles, Konferenzbeiträge)
- Monographien und Buchkapitel
- Hochschulschriften (Dissertationen, Masterarbeiten)
- Historische Archivdokumente (auch gescannt)
- Technische Berichte und Working Papers
- Mehrsprachige Korpora (EN, DE — weitere Sprachen ohne Anpassung möglich)

---

## Technologie-Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.12+ |
| CLI | Typer + Rich |
| Datenbank | SQLite (mit FTS5) |
| Wissensgraph | Oxigraph (pyoxigraph 0.5) |
| Vektorsuche | LanceDB |
| Embedding-Modell | `all-MiniLM-L6-v2` (lokal, offline nach erstem Download) |
| PDF-Verarbeitung | PyMuPDF |
| Keyword-Extraktion | YAKE + optional KeyBERT |
| Spracherkennung | lingua (offline) |
| GND-Erschließung | lobid.org API |
| RVK-Klassifikation | rvk.uni-regensburg.de API |

---

## Aktueller Stand

Phase 1 (März 2026) und Phase 2 (April 2026) sind abgeschlossen.
Testkorpus: 5 Dokumente (EN + DE), Ergebnisse:

| Metrik | Wert |
|---|---|
| Dokumenttyp-Genauigkeit | 100% |
| Titel-Extraktion | 100% |
| Autoren-Extraktion | 57% |
| Section-Tree F1 | 54% |
| Semantische Ähnlichkeit EN→EN | 0.595 |
| LanceDB Chunks | 2116 |
| Wissensgraph Tripel | 658 |

→ Roadmap: [`ROADMAP.md`](./ROADMAP.md)

---

## Verwandte Dokumente

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — Modulstruktur, Abhängigkeiten, Ingestion-Pipeline
- [`ARCHITECTURE-DU-PIPELINE.md`](./ARCHITECTURE-DU-PIPELINE.md) — Document-Understanding-Pipeline
- [`ARCHITECTURE-KNOWLEDGE-GRAPH.md`](./ARCHITECTURE-KNOWLEDGE-GRAPH.md) — Wissensgraph, Oxigraph, SPARQL
- [`ARCHITECTURE-EMBEDDINGS.md`](./ARCHITECTURE-EMBEDDINGS.md) — LanceDB, Chunk-Strategie, atlas similar
- [`DATABASE.md`](./DATABASE.md) — SQLite-Schema, Migrationen, Erschließungsspalten
- [`CLI.md`](./CLI.md) — Vollständige CLI-Referenz
- [`ROADMAP.md`](./ROADMAP.md) — Entwicklungsphasen und offene Entscheidungen
