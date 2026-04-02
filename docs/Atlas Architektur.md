# Atlas — Architektur

## Prinzip

Atlas ist ein einzelnes Python-Package (`src/atlas/`), das als
CLI-Werkzeug installiert wird. Es gibt keine Server, keine API,
keine getrennt deploybaren Dienste. Alles läuft im Prozess des
Nutzers, auf dem Rechner des Nutzers.

---

## Paketstruktur

```
src/atlas/
│
├── cli.py                    ← Einstiegspunkt, nur Routing
├── settings.py               ← Konfigurationshierarchie
│
├── common/                   ← Geteilte Utilities
│   └── hashing.py            ← SHA-256 für Dokument-Fingerprints
│
├── db/                       ← Datenbankschicht
│   ├── connection.py         ← connect() + get_connection() Kontext-Manager
│   │                           set_catalog_path() für alte extract/-Module
│   ├── migrate.py            ← Migration-Runner (schema_migrations-Tabelle)
│   └── migrations/           ← SQL-Migrationsdateien 0001–0014
│
├── catalog/                  ← Katalog-Lebenszyklus
│   ├── init.py               ← atlas init
│   ├── add.py                ← atlas add (Haupteinstiegspunkt)
│   ├── update.py             ← atlas update
│   └── remove.py             ← atlas remove
│
├── pipeline/                 ← Basis-Verarbeitungskette
│   ├── runner.py             ← run_pipeline(): geordneter Ablauf aller Schritte
│   │                           Schritte 1–12, inkl. Embeddings + Wissensgraph
│   ├── extract/
│   │   └── layout.py         ← Layout-Linien + Spans für DU
│   ├── detect/
│   │   └── language.py       ← Spracherkennung (lingua, offline)
│   └── normalize/
│       └── identifiers.py    ← Identifier normalisieren
│
├── extract/                  ← Rohe Extraktion (alte Architektur)
│   ├── text_pymupdf.py       ← Textextraktion via PyMuPDF
│   ├── text_fallback.py      ← pdftotext-Fallback
│   ├── pdf_metadata.py       ← PDF-Metadaten
│   ├── identifiers.py        ← DOI, arXiv, ISBN, PMID
│   └── authors.py            ← Autorenextraktion
│   Hinweis: Diese Module verwenden get_connection() intern.
│   runner.py ruft set_catalog_path() vor dem ersten Aufruf.
│
├── understanding/            ← Document Understanding (Phase 1)
│   ├── pipeline.py           ← Orchestrierung der DU-Stufen
│   ├── core/
│   │   ├── vocab.py          ← Rollennamen, Zonennamen, Signalnamen
│   │   ├── coordinate_system.py ← DocumentCoordinateSystem
│   │   ├── text_patterns.py  ← Geteilte Textmuster-Funktionen
│   │   ├── section_labels.py ← Sprachspezifische Section-Marker
│   │   └── style_model.py    ← Heading-Style-Clustering
│   ├── segmentation/
│   │   └── blocks.py         ← Zeilen → Blöcke
│   ├── measure/              ← Schicht 1: Messung
│   │   ├── geometry.py
│   │   ├── typography.py
│   │   ├── surface.py
│   │   ├── spacing.py
│   │   ├── furniture.py
│   │   ├── topology.py
│   │   ├── context.py
│   │   └── semantic_micro.py
│   ├── aggregate/            ← Schicht 2: Aggregation
│   │   └── signals.py
│   ├── interpret/            ← Schicht 3: Interpretation
│   │   ├── roles.py
│   │   ├── consensus.py
│   │   ├── headings.py
│   │   ├── zones.py
│   │   ├── section_tree.py
│   │   ├── document_type.py
│   │   ├── early_meta.py
│   │   └── toc.py
│   ├── persistence/
│   │   └── repository.py     ← SQLite-Backend für DU
│   └── eval.py               ← atlas dev eval (Ground-Truth-Vergleich)
│
├── knowledge/                ← Wissensgraph (Phase 2)
│   ├── store.py              ← KnowledgeStore: Oxigraph + Named Graphs
│   │                           add_doc_triples(), remove_document(), query()
│   ├── triples.py            ← write_document_to_store(): lokale Tripel
│   └── sparql.py             ← SPARQL-Queries für CLI-Kommandos
│                               alle Queries mit GRAPH ?g { ... }
│
├── embeddings/               ← Semantische Suche (Phase 2)
│   ├── store.py              ← EmbeddingStore: LanceDB, similar_documents()
│   ├── model.py              ← get_model() Singleton, embed_text()
│   └── index.py              ← index_document(), reindex_document()
│                               Chunk-Extraktion aus DU-Ergebnissen
│
├── enrich/                   ← Externe Anreicherung (Phase 2)
│   ├── keywords.py           ← YAKE (primär) + KeyBERT (optional)
│   │                           Input: Titel + Abstract + Seiten 0–2
│   ├── topic.py              ← GND-normalisiertes Hauptkonzept
│   │                           Pipeline: GND-IDs → lobid preferred label
│   ├── section_keywords.py   ← YAKE pro Section aus du_section_tree
│   ├── themes.py             ← Subjects via RVK-Labels / Wikidata
│   ├── gnd.py                ← GND-Entitäten via lobid.org
│   ├── rvk.py                ← RVK-Klassifikation via rvk.uni-regensburg.de
│   ├── wikidata.py           ← Wikidata QID + ORCID via Wikidata-API
│   ├── crossref.py           ← Vollständige Metadaten via DOI
│   └── orcid.py              ← ORCID-Disambiguierung
│
├── search/                   ← Suche (Phase 2 teilweise)
│   ├── fts.py                ← FTS5-Volltextsuche ✓
│   ├── structured.py         ← SQL-Abfragen (atlas find) ✓
│   ├── semantic.py           ← LanceDB-Vektorsuche (Phase 3)
│   └── fusion.py             ← Fusion-Ranking FTS5 + LanceDB (Phase 3)
│
├── inspect/                  ← Diagnose und Statusabfragen
│   └── (verschiedene Module)
│
└── export/                   ← Export (Phase 3)
    ├── bibtex.py
    ├── json.py
    └── csv.py
```

---

## Abhängigkeiten zwischen Modulen

```
cli.py
    → catalog/      (add, update, remove, init)
    → search/       (search, find)
    → embeddings/   (similar)
    → knowledge/    (refs, graph, concept)
    → enrich/       (enrich --keywords/--topic/--gnd/--rvk/...)
    → inspect/      (status, inspect, doctor)
    → export/       (export)

catalog/add.py
    → pipeline/runner.py   (Basis-Extraktion + DU + Embeddings + Graph)
    → enrich/keywords.py   (lokale Keyword-Extraktion nach atlas add)
    → db/                  (Persistenz)

pipeline/runner.py
    → extract/             (Text, Metadaten, Layout, Identifier)
    → normalize/           (Identifier)
    → understanding/       (DU-Pipeline)
    → pipeline/detect/     (Sprache)
    → embeddings/          (Vektorisierung, non-critical)
    → knowledge/           (Tripel-Erzeugung, non-critical)
    → db/connection.py     (set_catalog_path() Brücke für extract/)

understanding/
    → db/                  (nur via persistence/repository.py)
    → core/                (intern)
    Kennt knowledge/ und embeddings/ NICHT.

knowledge/
    → db/                  (liest Dokument-Metadaten)
    Kennt embeddings/ NICHT.

enrich/topic.py
    → enrich/gnd.py        (GND-IDs lesen)
    → lobid.org API        (preferred labels)

enrich/rvk.py
    → rvk.uni-regensburg.de API
    Nutzt GND über gnd.py als optionalen Zwischenschritt.
```

**Zentrale Architekturregeln:**

1. `understanding/` kennt `knowledge/` und `embeddings/` nicht.
2. `knowledge/` kennt `embeddings/` nicht.
3. `extract/`-Module verwenden `get_connection()` intern —
   `runner.py` ruft `set_catalog_path()` als ersten Schritt.
4. Embeddings und Wissensgraph sind non-critical in `runner.py` —
   Fehler werden geloggt, die Pipeline läuft weiter.

---

## Ingestion-Pipeline (atlas add)

```
atlas add <pdf>
    │
    ├─ 1. SHA-256 → document_id
    ├─ 2. Bereits indexiert? → skip
    ├─ 3. In documents registrieren (status: pending)
    │
    ├─── pipeline/runner.py ────────────────────────────────────
    │   ├─ set_catalog_path()           ← Brücke für extract/
    │   ├─ extract_text_pymupdf()       ← Text + Layout-Spans
    │   ├─ extract_pdf_metadata()       ← PDF-interne Metadaten
    │   ├─ run_extract_layout()         ← du_layout_lines/spans
    │   ├─ extract_identifiers()        ← DOI, ISBN, arXiv, PMID
    │   ├─ normalize_identifiers()      ← kanonische Formen
    │   ├─ run_du_pipeline()            ← Drei-Schichten-DU
    │   ├─ run_detect_language()        ← lingua offline
    │   ├─ _promote_du_metadata()       ← Titel/Autoren aus DU
    │   ├─ _promote_identifiers()       ← beste ID in documents
    │   ├─ _populate_knowledge_graph()  ← Tripel in Oxigraph
    │   ├─ _index_embeddings()          ← Chunks in LanceDB
    │   └─ _update_fts()               ← FTS5-Index
    │
    └─ enrich/keywords.py              ← YAKE lokal (kein Netz)
```

---

## Dateistruktur des Katalogs

```
~/Literatur/                        ← Wurzelordner der Sammlung
├── .atlas/
│   ├── catalog.db                  ← SQLite: Metadaten, DU, FTS5
│   ├── embeddings/                 ← LanceDB: Chunk-Vektoren
│   │   └── paragraphs.lance/
│   ├── knowledge/                  ← Oxigraph: Named Graphs
│   └── config.toml                 ← lokale Konfiguration
├── papers/
│   └── *.pdf
└── books/
    └── *.pdf

~/.atlas/                           ← globale Registry
├── registry.toml                   ← alle bekannten Kataloge
├── config.toml                     ← globale Defaults
└── models/
    └── all-MiniLM-L6-v2/           ← Embedding-Modell (einmalig)
```

---

## Konfigurationshierarchie

```
1. ~/.atlas/config.toml      ← globale Defaults (niedrigste Priorität)
2. .atlas/config.toml        ← katalogspezifische Überschreibungen
3. CLI-Flags                 ← einmalige Überschreibung (höchste Priorität)
```

---

## Zwei Architekturstile im selben Paket

Atlas hat zwei Codegenerationen die koexistieren:

**Neue Architektur** (`catalog/`, `pipeline/runner.py`, `understanding/`,
`knowledge/`, `embeddings/`, `enrich/`): Verbindung wird explizit
übergeben. `connect(db_path)` → Caller verwaltet Lifecycle.

**Alte Architektur** (`extract/`, `normalize/`, `segment/`): Module
öffnen ihre eigene Verbindung via `get_connection()` als Kontext-Manager.
Konfiguriert durch `set_catalog_path(catalog_root)` in `runner.py`.

Die Brücke zwischen beiden: `db/connection.py` exportiert beide
Interfaces. `runner.py` ruft `set_catalog_path()` als ersten Schritt,
damit alle nachfolgenden `get_connection()`-Aufrufe den richtigen
Katalog finden.

---

## Designprinzipien

**Lokalität.** Kein Dokument verlässt den Rechner des Nutzers,
außer bei explizit angeforderten Anreicherungsoperationen
(`atlas enrich --crossref`, `--wikidata` etc.).

**Idempotenz.** Alle Verarbeitungsschritte können wiederholt werden.
`atlas add` auf ein bereits indexiertes Dokument überspringt es.
`atlas dev du process <id>` überschreibt DU-Ergebnisse sauber.

**Schichtentrennung.** `understanding/` kennt `knowledge/` nicht.
`knowledge/` kennt `embeddings/` nicht. Non-critical Steps
(Embeddings, Wissensgraph) werden in `runner.py` mit try/except
umhüllt — ein Fehler dort stoppt nicht die gesamte Pipeline.

**Explizite Fehler.** Fehler landen immer mit einem Hinweis auf
den nächsten sinnvollen Schritt. Stille Fehler werden vermieden.

→ Document Understanding: [`ARCHITECTURE-DU-PIPELINE.md`](./ARCHITECTURE-DU-PIPELINE.md)
→ Wissensgraph: [`ARCHITECTURE-KNOWLEDGE-GRAPH.md`](./ARCHITECTURE-KNOWLEDGE-GRAPH.md)
→ Embeddings: [`ARCHITECTURE-EMBEDDINGS.md`](./ARCHITECTURE-EMBEDDINGS.md)
→ Datenbankschema: [`DATABASE.md`](./DATABASE.md)
