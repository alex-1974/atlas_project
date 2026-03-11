# Atlas Development Roadmap

This document tracks open development work for Atlas.

The current system is functionally complete for ingestion, extraction,
metadata enrichment, segmentation and search.

Future work focuses on improving metadata quality and semantic exploration.

---

# Current State

Implemented:

* document discovery and registration
* PDF text extraction
* metadata extraction
* identifier extraction
* identifier normalization
* identifier deduplication
* title heuristics
* OCR candidate detection
* paragraph segmentation
* TF-IDF search
* corpus inspection tools

---

# High Priority

## Author Extraction

Extract author names from:

* PDF metadata
* title pages
* first page text

Goals:

* authors table
* document_author relationships
* normalized author names

---

## DOI Metadata Enrichment

If a DOI is known:

Fetch metadata from Crossref.

Retrieve:

* title
* authors
* publication year
* journal or book title

Benefits:

* canonical metadata
* higher data quality

---

## Improved Title Detection

Improve current heuristics for:

* theses
* multi-line titles
* scanned PDFs

Possible improvements:

* merge adjacent title lines
* detect title blocks
* stronger filtering of institutional text

---

# Medium Priority

## Topic Classification

Automatically derive document topics.

Possible approaches:

* TF-IDF clustering
* LDA topic models
* embedding clustering

Tables:

topics
document_topics

Benefits:

* automatic literature taxonomy
* thematic browsing

---

## Semantic Search

Augment TF-IDF search with embeddings.

Possible models:

* sentence-transformers
* bge models
* instructor models

Database storage:

text_segments.embedding

Benefits:

* concept search
* similarity search

---

## Citation Extraction

Extract references from bibliography sections.

Goals:

* identify cited works
* build citation graph

Tables:

citations
document_citations

Benefits:

* literature networks
* influence tracking

---

# Low Priority

## OCR Integration

Automatically OCR documents marked:

needs_ocr = true

Possible tools:

* Tesseract
* OCRmyPDF

---

## Web Interface

Optional UI:

* document browser
* search interface
* corpus statistics

Possible stack:

* FastAPI
* lightweight frontend

---

# Long Term Vision

Atlas evolves into a **local research knowledge graph**:

* document graph
* author graph
* citation graph
* topic graph
* semantic search

The system remains:

* deterministic
* local-first
* scriptable
* reproducible

