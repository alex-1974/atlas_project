# Atlas — Literature Knowledge Base

Atlas is a research tool for building a structured knowledge base from large collections of scientific PDFs. It ingests documents, extracts text and metadata, identifies persistent identifiers (DOI, ISBN, ISSN, URN), and provides searchable text segments for exploration.

The system is designed for local research workflows, reproducible data processing, and incremental enrichment of document metadata.

Typical use case:

* maintain a curated library of PDFs
* extract machine-readable knowledge from them
* search the corpus efficiently
* identify related literature

Atlas is currently used to support research pipelines such as the **BVILLAGE historical architecture project**.

---

# Architecture

Atlas processes documents in a deterministic pipeline:

discover
↓
register
↓
extract-text
↓
extract-metadata
↓
extract-identifiers
↓
normalize-identifiers
↓
dedupe-identifiers
↓
enrich-title-text
↓
enrich-title-filename
↓
enrich-quality
↓
mark-ocr-candidates
↓
segment-paragraphs
↓
search

Each stage is implemented as an independent module and exposed via the CLI.

---

# Project Structure

atlas/

cli.py — Command line interface
config.py — Configuration loading

db/ — Database connection and migrations

ingest/ — Document discovery and registration

extract/ — Text and metadata extraction

enrich/ — Metadata enrichment heuristics

normalize/ — Identifier normalization

segment/ — Text segmentation

search/ — Corpus search

inspect/ — Diagnostics and corpus inspection

util/ — Small utilities

---

# Requirements

Python 3.12+
PostgreSQL
pdftotext (poppler-utils)

---

# Installation

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

---

# Database

ATLAS_CONFIG=atlas.yaml python -m atlas.cli migrate

---

# Typical Workflow

atlas discover
atlas register

atlas extract-text
atlas extract-metadata

atlas extract-identifiers
atlas normalize-identifiers
atlas dedupe-identifiers

atlas enrich-title-text
atlas enrich-title-filename
atlas enrich-quality
atlas mark-ocr-candidates

atlas segment-paragraphs

atlas search-docs "half timbered house joinery"

---

# Current Capabilities

* PDF text extraction
* metadata extraction
* identifier mining
* heuristic title detection
* OCR candidate detection
* paragraph segmentation
* TF-IDF search

---

# Project Status

Atlas is stable for medium-sized research corpora.

Future work focuses on semantic search, citation graphs and automatic topic classification.

See **DEV_ROADMAP.md**.

