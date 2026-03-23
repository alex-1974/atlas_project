# Atlas

> A local, structured knowledge base for scientific literature.  
> No cloud. No server. No lock-in.

Atlas catalogs a collection of PDFs the way Git versions a codebase. Run `atlas init` in any folder, and that folder becomes a searchable, structured, interconnected knowledge base — stored entirely in `.atlas/`, portable as a directory, and fully reproducible.

---

## What Atlas Does

Atlas processes scientific PDFs through a deterministic pipeline and builds three complementary layers of knowledge:

**A full-text catalog** (`catalog.db`) — structured metadata, extracted text, FTS5 search. Find any paper by keyword, author, year, DOI, or classification.

**Semantic vectors** (`embeddings/`) — each document is represented as a vector. Search by meaning, not just by words. Find papers on a topic even when they never use your exact search terms.

**A knowledge graph** (`knowledge/`) — relationships between documents, authors, and concepts stored as RDF triples. Query citation networks, co-author graphs, and concept clusters via SPARQL.

The deepest layer is **Document Understanding** — a structural analysis pipeline that reads each PDF block by block, identifies zones (front matter, body, back matter), extracts the section tree, recognizes headings, references, captions, and abstract, and classifies the document type. Everything else — embeddings, graph triples, extracted metadata — is built on top of this foundation.

---

## Installation

```bash
git clone <repo>
cd atlas
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requirements: Python 3.12+, `pdftotext` (poppler-utils)

---

## Quickstart

```bash
cd ~/Literatur
atlas init

atlas add paper.pdf
atlas add .               # index all PDFs in this folder

atlas search "half-timbered house joinery"
atlas search --semantic "structural analysis of wooden buildings"
atlas find --author "Binding"
atlas find --year 2010-2020

atlas inspect <id>        # document structure, zones, section tree
atlas similar <id>        # find related papers
atlas refs <id>           # citation network
```

---

## How It Works

### The Pipeline

Every document passes through a fixed sequence of stages:

```
extract_text → extract_metadata → extract_identifiers → extract_authors
→ normalize_identifiers → enrich_titles → enrich_quality → enrich_ocr
→ segment → du → embedding → graph
```

Each stage writes to `catalog.db` and records its status in `pipeline_stages`. A failed or outdated stage can be rerun without reprocessing the entire document. Atlas resumes interrupted indexing runs automatically.

### Document Understanding

The `du` stage is the analytical core of Atlas. It processes each PDF at the layout-block level through a sequence of layers:

- **Low-level layers** — geometry, typography, spacing, surface features, topology
- **Signal layers** — block-level signals: `heading_like`, `reference_like`, `caption_like`
- **Role inference** — discrete block roles: `heading`, `body`, `title`, `reference`, `caption`, `noise`
- **Zones** — global document regions: `front`, `body`, `back`
- **Section tree** — hierarchical heading structure with levels
- **Document type** — `journal_article`, `archival_text`, and more

The results feed directly into metadata extraction (title, authors, abstract), embedding selection, and knowledge graph construction.

### Three Storage Layers

| Layer | Technology | Location | Purpose |
|---|---|---|---|
| Catalog | SQLite + FTS5 | `.atlas/catalog.db` | Metadata, full text, search index |
| Embeddings | LanceDB | `.atlas/embeddings/` | Semantic vectors |
| Knowledge graph | Oxigraph | `.atlas/knowledge/` | RDF triples, SPARQL |

SQLite is the single source of truth. The graph is a projection of SQL data, rebuilt on demand.

### Identity

Every document is identified by the SHA-256 hash of its PDF file. Moving or renaming a file does not change its identity. The same file found twice is flagged as a duplicate, not re-indexed.

---

## Project Structure

```
~/Literatur/                ← your literature folder
├── .atlas/
│   ├── catalog.db          ← SQLite: metadata, full text, FTS5
│   ├── embeddings/         ← LanceDB: semantic vectors
│   ├── knowledge/          ← Oxigraph: knowledge graph
│   ├── ontology.ttl        ← RDF ontology definition
│   └── config.toml         ← local configuration
└── papers/
    └── *.pdf

~/.atlas/                   ← global registry
├── registry.toml           ← all known catalogs
├── config.toml             ← global defaults
└── models/
    └── all-MiniLM-L6-v2/  ← shared embedding model
```

Each catalog is fully self-contained. Copy the folder, and everything moves with it.

---

## CLI Reference

### Catalog

```bash
atlas init                  # initialize a catalog in the current folder
atlas add <pdf|folder>      # index one PDF or all PDFs in a folder
atlas update                # detect and index new PDFs
atlas remove <id>           # remove a document from all layers
```

### Search

```bash
atlas search "<query>"                  # full-text search (FTS5)
atlas search --semantic "<query>"       # semantic search (LanceDB)
atlas find --author "Name"
atlas find --year 2010-2020
atlas find --doi "10.1234/..."
atlas find --rvk "ST 301"
atlas similar <id>                      # find related documents
```

### Knowledge Graph

```bash
atlas refs <id>                         # citation network
atlas graph --author "Name"             # co-author graph
atlas concept "Begriff"                 # linked documents and concepts
```

### Enrichment

```bash
atlas enrich <id>                       # enrich a single document
atlas enrich --all --crossref           # enrich catalog via CrossRef
atlas enrich --all --wikidata
atlas enrich --all --gnd
```

### Overview

```bash
atlas status                            # catalog size, pipeline state
atlas inspect <id>                      # document structure and metadata
atlas doctor                            # consistency check
```

### Global

```bash
atlas global status                     # all known catalogs
atlas global search "<query>"           # search across all catalogs
```

### Export

```bash
atlas export --bibtex
atlas export --json
atlas export --csv
```

---

## Configuration

Configuration is layered: global defaults, overridden by local values, overridden by CLI flags.

```toml
# .atlas/config.toml

[atlas]
language = "de"

[embeddings]
model = "all-MiniLM-L6-v2"

[index]
include = ["**/*.pdf"]
exclude = ["archive/", "tmp/"]

[wikidata]
enabled = true
auto_enrich = false

[rvk]
enabled = true
```

---

## External Enrichment

Atlas can pull metadata from external sources. All enrichment is optional and additive — no document depends on it, and Atlas works fully offline without it.

| Source | What it adds |
|---|---|
| CrossRef | Title, authors, year, abstract (highest priority) |
| arXiv | Metadata for arXiv papers |
| Wikidata | Linked entity identifiers (`owl:sameAs`) |
| GND | Controlled subject keywords |
| RVK | Library classification |

Metadata conflicts are resolved by a fixed priority chain: `CrossRef > DU extraction > PDF metadata > filename`.

---

## Status

Atlas is under active development. The base pipeline (text extraction, metadata, search) is operational. Document Understanding is implemented and running. Semantic search, knowledge graph, and external enrichment are being built as part of the current rebuild.

See [`atlas-rebuild-roadmap-v3.md`](./docs/atlas-rebuild-roadmap-v3.md) for the full implementation plan.

---

## Background

Atlas is developed to support the **BVILLAGE** historical architecture research project — a corpus-based investigation of vernacular building traditions. The tool grew from the need to search, structure, and connect several hundred specialist PDFs that standard reference managers handle poorly.

The name reflects the ambition: not just an index, but a map.
