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
├── core/                     ← Geteilte Utilities
│   ├── logging.py            ← Zentrales Logging (ATLAS_LOG-Env)
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
│   ├── profiling.py          ← Pass 0: DocumentProfile (book/structure score)
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
├── understanding/            ← Document Understanding
│   ├── pipeline.py           ← Orchestrierung der DU-Stufen
│   ├── core/
│   │   ├── vocab.py          ← Rollennamen, Zonennamen, Signalnamen
│   │   ├── coordinate_system.py ← DocumentCoordinateSystem
│   │   ├── text_patterns.py  ← Geteilte Textmuster-Funktionen
│   │   ├── section_labels.py ← Sprachspezifische Section-Marker
│   │   └── style_model.py    ← Heading-Style-Clustering (Fallback)
│   ├── segmentation/
│   │   └── blocks.py         ← Zeilen → Blöcke, source_kind-Erkennung
│   ├── measure/              ← Schicht 1: Messung
│   │   ├── geometry.py       ← Position, Breite, Abstände (absolute pt)
│   │   ├── typography.py     ← font_size, bold, italic, color
│   │   ├── surface.py        ← word_count, ends_with_colon, all_caps, ...
│   │   ├── spacing.py        ← paragraph_gap, in_flow_score
│   │   ├── furniture.py      ← running_header_like, repeated_across_pages
│   │   ├── topology.py       ← Nachbarschaftsbeziehungen
│   │   ├── context.py        ← doc_y_ratio, page_y_ratio
│   │   ├── semantic_micro.py ← Markwords: is_references_marker, ...
│   │   └── typography_profile.py  ← TypographyProfile (body_font,
│   │                                 gap_norm, font_classes) [Phase 3]
│   ├── aggregate/            ← Schicht 2: Aggregation
│   │   └── signals.py        ← Dokumentrelative Signalaggregation
│   ├── graph/                ← Nachbarschaftsgraph-Korrekturen
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   ├── corrections.py
│   │   └── edges.py
│   ├── interpret/            ← Schicht 3: Interpretation
│   │   ├── roles.py          ← Rollenklassifikation
│   │   ├── consensus.py      ← Konsensus-Ausgleich
│   │   ├── zones.py          ← FRONT_MATTER | BODY | BACK_MATTER
│   │   ├── anchor_detection.py  ← Hochkonfidente Anker + HeadingPatterns
│   │   │                          [Phase 3, neu]
│   │   ├── headings.py       ← Heading-Kandidaten (Pattern-basiert)
│   │   ├── section_tree.py   ← Hierarchischer Section Tree (L1–L3)
│   │   ├── document_type.py  ← Dokumenttyp-Klassifikation
│   │   ├── early_meta.py     ← Frühe Metadaten-Extraktion
│   │   └── toc.py            ← TOC-Erkennung und -Merge
│   ├── persistence/
│   │   └── repository.py     ← SQLite-Backend für DU
│   └── eval.py               ← atlas dev eval (Ground-Truth-Vergleich)
│
├── knowledge/                ← Wissensgraph
│   ├── store.py              ← KnowledgeStore: Oxigraph + Named Graphs
│   ├── triples.py            ← write_document_to_store(): lokale Tripel
│   └── sparql.py             ← SPARQL-Queries für CLI-Kommandos
│
├── embeddings/               ← Semantische Suche
│   ├── store.py              ← EmbeddingStore: LanceDB, similar_documents()
│   ├── model.py              ← get_model() Singleton, embed_text()
│   └── index.py              ← index_document(), reindex_document()
│
├── enrich/                   ← Externe Anreicherung
│   ├── keywords.py           ← YAKE (primär) + KeyBERT (optional)
│   ├── topic.py              ← GND-normalisiertes Hauptkonzept
│   ├── section_keywords.py   ← YAKE pro Section aus du_section_tree
│   ├── themes.py             ← Subjects via RVK-Labels / Wikidata
│   ├── gnd.py                ← GND-Entitäten via lobid.org
│   ├── rvk.py                ← RVK-Klassifikation
│   ├── wikidata.py           ← Wikidata QID + ORCID
│   ├── crossref.py           ← Vollständige Metadaten via DOI
│   └── orcid.py              ← ORCID-Disambiguierung
│
├── search/                   ← Suche
│   ├── fts.py                ← FTS5-Volltextsuche ✓
│   ├── structured.py         ← SQL-Abfragen (atlas find) ✓
│   ├── semantic.py           ← LanceDB-Vektorsuche [Phase 3]
│   └── fusion.py             ← Fusion-Ranking FTS5 + LanceDB [Phase 3]
│
├── inspect/                  ← Diagnose und Statusabfragen
│   └── (verschiedene Module)
│
└── export/                   ← Export [Phase 3]
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
    → db/

pipeline/runner.py
    → pipeline/profiling.py        (Pass 0: DocumentProfile)
    → extract/                     (Text, Metadaten, Layout, Identifier)
    → normalize/                   (Identifier)
    → understanding/               (DU-Pipeline)
    → pipeline/detect/             (Sprache)
    → embeddings/                  (Vektorisierung, non-critical)
    → knowledge/                   (Tripel-Erzeugung, non-critical)

understanding/pipeline.py
    → segmentation/blocks.py       (Pass 1: Segmentierung)
    → measure/*.py                 (Pass 1: Messung)
    → measure/typography_profile.py (Pass 1.5: TypographyProfile)
    → aggregate/signals.py         (Pass 2: Aggregation)
    → graph/                       (Pass 2.5: Korrekturen)
    → interpret/roles.py           (Pass 3.1)
    → interpret/consensus.py       (Pass 3.2)
    → interpret/zones.py           (Pass 3.3)
    → interpret/anchor_detection.py (Pass 3.4: HeadingPatterns)
    → interpret/headings.py        (Pass 3.5)
    → interpret/section_tree.py    (Pass 3.6)
    → interpret/document_type.py   (Pass 3.7)

understanding/
    → db/                  (nur via persistence/repository.py)
    Kennt knowledge/ und embeddings/ NICHT.

knowledge/
    → db/                  (liest Dokument-Metadaten)
    Kennt embeddings/ NICHT.
```

**Zentrale Architekturregeln:**
1. `understanding/` kennt `knowledge/` und `embeddings/` nicht.
2. `knowledge/` kennt `embeddings/` nicht.
3. Alle DU-Signale sind dokumentrelativ — keine absoluten Schwellenwerte.
4. Embeddings und Wissensgraph sind non-critical in `runner.py`.
5. Opportunistisch: kein Pattern → kein Section Tree, kein Raten.

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
    │   ├─ set_catalog_path()
    │   ├─ profile_document()          ← Pass 0: DocumentProfile
    │   ├─ extract_text_pymupdf()
    │   ├─ extract_pdf_metadata()
    │   ├─ run_extract_layout()
    │   ├─ extract_identifiers()
    │   ├─ normalize_identifiers()
    │   ├─ run_du_pipeline()           ← DU: Pass 1–3 (s.u.)
    │   ├─ run_detect_language()
    │   ├─ _promote_du_metadata()
    │   ├─ _promote_identifiers()
    │   ├─ _populate_knowledge_graph()
    │   ├─ _index_embeddings()
    │   └─ _update_fts()
    │
    └─ enrich/keywords.py             ← YAKE lokal (kein Netz)

run_du_pipeline() intern:
    ├─ build_document()               ← Segmentierung, source_kind
    ├─ compute_geometry/typography/surface/... ← Layer 1
    ├─ build_typography_profile()     ← Pass 1.5
    ├─ compute_signals()              ← Layer 2 (dokumentrelativ)
    ├─ run_graph_corrections()        ← Pass 2.5
    │
    │  [Pass 1: ohne Dokumenttyp]
    ├─ compute_roles()
    ├─ compute_consensus()
    ├─ compute_zones()
    ├─ detect_anchors()               ← Pass 3.4 (neu)
    ├─ compute_headings()
    ├─ compute_section_tree()
    ├─ compute_document_type()        ← erkennt Typ aus Pass-1-Ergebnissen
    │
    │  [Pass 2: mit Dokumenttyp]
    ├─ compute_roles()
    ├─ compute_consensus()
    ├─ compute_zones()
    ├─ detect_anchors()
    ├─ compute_headings()
    └─ compute_section_tree()
```

---

## Logging

`atlas.core.logging` stellt eine lazy Logger-Hierarchie bereit:

```
atlas                     — root
atlas.pipeline            — run_pipeline, Pass 0
atlas.du                  — DU root
atlas.du.segmentation     — source_kind-Erkennung
atlas.du.zones            — Zonengrenzen
atlas.du.headings         — Kandidaten-Anzahl
atlas.du.section_tree     — Section-Anzahl
atlas.du.document_type    — Typ-Scores
atlas.du.typography_profile — body_font, gap_norm, font_classes
atlas.enrich / atlas.search / atlas.knowledge / atlas.embeddings
```

Steuerung via Umgebungsvariable:
```bash
ATLAS_LOG=INFO atlas add paper.pdf
ATLAS_LOG=atlas.du=DEBUG atlas dev du process fd2ec5
ATLAS_LOG=atlas.du.zones=DEBUG,atlas.pipeline=INFO atlas add paper.pdf
```

---

## Dateistruktur des Katalogs

```
~/Literatur/
├── .atlas/
│   ├── catalog.db          ← SQLite: Metadaten, DU, FTS5
│   ├── embeddings/         ← LanceDB: Chunk-Vektoren
│   ├── knowledge/          ← Oxigraph: Named Graphs
│   └── config.toml
└── papers/
    └── *.pdf

~/.atlas/
├── registry.toml
├── config.toml
└── models/
    └── all-MiniLM-L6-v2/
```

---

## Designprinzipien

**Lokalität.** Kein Dokument verlässt den Rechner des Nutzers außer
bei explizit angeforderten Anreicherungsoperationen.

**Idempotenz.** Alle Verarbeitungsschritte können wiederholt werden.

**Dokumentrelativität.** Fontgröße, Abstände und Farben werden immer
relativ zu den Normen des jeweiligen Dokuments gemessen.

**Opportunismus.** Atlas erkennt Struktur wenn sie vorhanden und
erkennbar ist. Ohne hochkonfidentes Pattern bleibt der Section Tree
leer — das ist korrekt und besser als geraten.

**Schichtentrennung.** `understanding/` kennt `knowledge/` nicht.
`knowledge/` kennt `embeddings/` nicht.

**Explizite Fehler.** Fehler landen immer mit einem Hinweis auf
den nächsten sinnvollen Schritt. Stille Fehler werden vermieden.

→ Document Understanding: [`ARCHITECTURE-DU-PIPELINE.md`](./ARCHITECTURE-DU-PIPELINE.md)
→ Wissensgraph: [`ARCHITECTURE-KNOWLEDGE-GRAPH.md`](./ARCHITECTURE-KNOWLEDGE-GRAPH.md)
→ Embeddings: [`ARCHITECTURE-EMBEDDINGS.md`](./ARCHITECTURE-EMBEDDINGS.md)
→ Datenbankschema: [`DATABASE.md`](./DATABASE.md)
