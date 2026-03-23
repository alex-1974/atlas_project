# Atlas — Projektstruktur

> Referenzdokument für [`atlas-rebuild-roadmap.md`](./atlas-rebuild-roadmap.md)  
> Paketlayout, Modulübersicht und Zuordnung alt → neu.

---

## Neues Paketlayout

```
src/atlas/
├── cli.py                        ← Einstiegspunkt, nur Routing
├── settings.py                   ← Konfigurationshierarchie
│
├── common/                       ← Utilities
│   ├── hashing.py                ← SHA-256 (unverändert aus common/hashing.py)
│   └── __init__.py
│
├── db/                           ← Datenbankschicht
│   ├── connection.py             ← SQLite-Verbindung (neu, ersetzt psycopg)
│   ├── migrate.py                ← Migration-Runner für SQLite (neu)
│   └── __init__.py
│
├── catalog/                      ← Katalog-Lebenszyklus
│   ├── init.py                   ← atlas init
│   ├── add.py                    ← atlas add
│   ├── update.py                 ← atlas update
│   ├── remove.py                 ← atlas remove
│   └── __init__.py
│
├── pipeline/                     ← Interne Verarbeitungskette
│   ├── runner.py                 ← geordneter Ablauf aller Schritte
│   ├── extract/
│   │   ├── text.py               ← aus extract/text_pymupdf.py + text_fallback.py
│   │   ├── metadata.py           ← aus extract/pdf_metadata.py
│   │   ├── identifiers.py        ← aus extract/identifiers.py
│   │   └── authors.py            ← aus extract/authors.py
│   ├── enrich/
│   │   ├── titles.py             ← aus enrich/title_from_text.py + title_from_filename.py + pdf_metadata_titles.py
│   │   ├── quality.py            ← aus enrich/quality.py
│   │   └── ocr.py                ← aus enrich/ocr_candidates.py
│   ├── normalize/
│   │   └── identifiers.py        ← aus normalize/identifiers.py
│   └── segment/
│       └── paragraphs.py         ← aus segment/paragraphs.py
│
├── understanding/                ← Document Understanding (portiert, nicht neu geschrieben)
│   ├── pipeline.py               ← geordnete compute_*-Kette
│   ├── layers/                   ← aus document_understanding/layers/
│   │   ├── geometry.py
│   │   ├── typography.py
│   │   ├── surface.py
│   │   ├── context.py
│   │   ├── semantic_micro.py
│   │   ├── spacing_rhythm.py
│   │   ├── topology.py
│   │   ├── page_furniture.py
│   │   ├── document_phase.py
│   │   ├── section_tree.py
│   │   └── zones.py
│   ├── inference/                ← aus document_understanding/inference/
│   │   ├── signals.py
│   │   ├── roles.py
│   │   ├── consensus.py
│   │   ├── headings.py
│   │   ├── zone_hypotheses.py
│   │   ├── zone_memberships.py
│   │   ├── zones.py
│   │   ├── semantic_zones.py
│   │   ├── document_type.py
│   │   ├── document_model.py
│   │   └── early_meta.py
│   ├── layout/                   ← aus document_understanding/layout/
│   │   ├── layout_graph.py
│   │   └── layout_clusters.py
│   ├── segmentation/             ← aus document_understanding/segmentation/
│   │   ├── blocks.py
│   │   └── block_segmentation.py
│   ├── core/                     ← aus document_understanding/core/
│   │   ├── models.py
│   │   ├── coordinate_system.py
│   │   ├── normalization.py
│   │   ├── heading_candidates.py
│   │   ├── heading_normalization.py
│   │   ├── style_model.py
│   │   └── title_model.py
│   └── persistence/
│       └── repository.py         ← SQLite-Backend (neu geschrieben, gleiche Signaturen)
│
├── knowledge/                    ← Wissensgraph (neu)
│   ├── store.py                  ← Oxigraph-Verbindung
│   ├── triples.py                ← Tripel-Erzeugung
│   ├── sparql.py                 ← SPARQL-Abfragen
│   └── __init__.py
│
├── embeddings/                   ← Semantische Suche (neu)
│   ├── store.py                  ← LanceDB-Verbindung
│   ├── model.py                  ← Embedding-Modell, Cache-Verwaltung
│   └── __init__.py
│
├── search/                       ← Suche über alle Schichten
│   ├── fts.py                    ← FTS5-Suche
│   ├── semantic.py               ← LanceDB-Suche
│   ├── structured.py             ← SQL-Abfragen
│   ├── fusion.py                 ← Ergebnisse zusammenführen und ranken
│   └── __init__.py
│
├── enrich/                       ← Externe Anreicherung (neu)
│   ├── crossref.py
│   ├── wikidata.py
│   ├── gnd.py
│   ├── arxiv.py
│   ├── rvk.py
│   └── __init__.py
│
├── inspect/                      ← Diagnose und Statusabfragen
│   ├── overview.py               ← atlas status
│   ├── document.py               ← atlas inspect <id>
│   ├── doctor.py                 ← atlas doctor
│   └── __init__.py
│
├── export/                       ← Export (neu)
│   ├── bibtex.py
│   ├── json.py
│   ├── csv.py
│   └── __init__.py
│
└── models/                       ← Datenmodelle
    ├── records.py                ← aus models/records.py (unverändert)
    └── __init__.py
```

---

## Zuordnung alt → neu

| Bestehendes Modul | Neues Modul | Anmerkung |
|---|---|---|
| `ingest/discovery.py` | `catalog/add.py` | Logik integriert |
| `ingest/registration.py` | `catalog/add.py` | Logik integriert |
| `extract/text_pymupdf.py` | `pipeline/extract/text.py` | Port |
| `extract/text_fallback.py` | `pipeline/extract/text.py` | Zusammengeführt |
| `extract/pdf_metadata.py` | `pipeline/extract/metadata.py` | Port |
| `extract/identifiers.py` | `pipeline/extract/identifiers.py` | Port |
| `extract/authors.py` | `pipeline/extract/authors.py` | Port |
| `enrich/title_from_text.py` | `pipeline/enrich/titles.py` | Zusammengeführt |
| `enrich/title_from_filename.py` | `pipeline/enrich/titles.py` | Zusammengeführt |
| `enrich/pdf_metadata_titles.py` | `pipeline/enrich/titles.py` | Zusammengeführt |
| `enrich/quality.py` | `pipeline/enrich/quality.py` | Port |
| `enrich/ocr_candidates.py` | `pipeline/enrich/ocr.py` | Port |
| `normalize/identifiers.py` | `pipeline/normalize/identifiers.py` | Port |
| `segment/paragraphs.py` | `pipeline/segment/paragraphs.py` | Port |
| `document_understanding/layers/` | `understanding/layers/` | Port, gleiche Logik |
| `document_understanding/inference/` | `understanding/inference/` | Port, gleiche Logik |
| `document_understanding/layout/` | `understanding/layout/` | Port |
| `document_understanding/segmentation/` | `understanding/segmentation/` | Port |
| `document_understanding/core/` | `understanding/core/` | Port |
| `document_understanding/persistence/repository.py` | `understanding/persistence/repository.py` | Neu: SQLite-Backend, gleiche Signaturen |
| `search/lexical.py` | `search/fts.py` | Port |
| `search/document_search.py` | `search/fusion.py` | Erweitert |
| `inspect/overview.py` | `inspect/overview.py` | Port |
| `inspect/` (weitere) | `inspect/document.py` | Zusammengeführt |
| `structure/` | `pipeline/extract/` | Logik integriert |
| `lexicon/` | `pipeline/extract/` | Integriert |
| `nlp/` | `pipeline/extract/authors.py` | Integriert |
| — | `knowledge/` | Neu |
| — | `embeddings/` | Neu |
| — | `enrich/` | Neu (externe Anreicherung) |
| — | `export/` | Neu |

---

## Was wegfällt

| Bestehendes Modul | Grund |
|---|---|
| `db/connection.py` (psycopg) | Ersetzt durch SQLite-Verbindung |
| `eval/` | Wird in `atlas dev eval` integriert |
| `enrich/document_state.py` | Zustandslogik in `catalog/` integriert |
| `segment/block_evidence.py` | In `understanding/` integriert |
| `segment/region_assembly.py` | In `understanding/` integriert |

---

## Dateistruktur des Katalogs

```
~/Literatur/                        ← Wurzelordner der Sammlung
├── .atlas/
│   ├── catalog.db                  ← SQLite: Metadaten, Volltext, FTS5
│   ├── embeddings/                 ← LanceDB: Vektoren
│   ├── knowledge/                  ← Oxigraph: Wissensgraph
│   ├── ontology.ttl                ← Ontologie-Definition
│   └── config.toml                 ← lokale Konfiguration
├── papers/
│   └── *.pdf
└── books/
    └── *.pdf

~/.atlas/                           ← globale Registry
├── registry.toml                   ← alle bekannten Kataloge
├── config.toml                     ← globale Defaults
└── models/
    └── all-MiniLM-L6-v2/           ← Embedding-Modell (einmal, für alle Kataloge)
```
