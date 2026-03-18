# Atlas Document Understanding Architecture

**Layered Blueprint for Document Structure Reconstruction**

---

# 1. Purpose

The Atlas Document Understanding (DU) system reconstructs the structure of arbitrary scientific and historical documents (PDFs, scans, essays, books, reports) by combining multiple independent analytical layers.

No single signal determines the role of a text block.
Instead, structure emerges from the **superposition of multiple layers of evidence**.

This design makes the system robust against:

* layout variations
* missing numbering
* OCR noise
* inconsistent typography
* heterogeneous document genres

The architecture follows a **layered blueprint model** where each layer contributes orthogonal information about the document.

---

# 2. Conceptual Model

Each document is decomposed into **blocks** (text segments extracted from the PDF).

For every block, Atlas computes multiple feature layers.

```
Raw Document
      │
      ▼
Text Blocks
      │
      ▼
Feature Layers
      │
      ▼
Structural Signals
      │
      ▼
Block Roles
      │
      ▼
Semantic Zones
      │
      ▼
Document Structure
```

The system therefore separates:

* **Observation layers** (what we measure)
* **Interpretation layers** (what the measurements imply)

---

# 3. Block as the Central Data Unit

All analysis operates on the concept of a **block**.

A block is a spatially coherent text segment extracted from the PDF.

Typical properties:

```
block_id
document_id
page_index
block_index

text
x0
y0
x1
y1
```

Blocks represent the minimal unit from which structure is reconstructed.

---

# 4. Layer Architecture

Atlas separates feature extraction into several independent layers.

Each layer captures a different dimension of document structure.

---

# 5. Geometry Layer

The geometry layer describes the **spatial arrangement** of blocks on the page.

This layer captures visual layout structure independent of the textual content.

### Typical Features

```
x0, y0, x1, y1
width
height

relative_width
relative_height

centeredness
indent_left
indent_right

whitespace_before
whitespace_after

distance_to_previous_block
distance_to_next_block

near_page_top
near_page_bottom

column_index
column_width_ratio
```

### Questions answered

The geometry layer answers questions such as:

* Is the block visually isolated?
* Is it centered?
* Is it indented?
* Does it begin a new visual paragraph?
* Is it located in a header or footer region?
* Does it occupy full column width?

Geometry is the **most robust layout signal** across document types.

---

# 6. Typography Layer

The typography layer captures the **visual style of text**.

It describes how the text is rendered rather than where it appears.

### Typical Features

```
font_family
font_size
font_size_relative_document
font_size_relative_page

bold
italic
small_caps
all_caps

font_color
font_weight

font_change_from_previous_block
font_change_from_next_block
```

### Questions answered

Typography signals allow the system to infer:

* visual prominence
* heading likelihood
* caption style
* emphasized labels
* authorship lines

Typography is critical for detecting:

* titles
* section headings
* captions
* figure labels

---

# 7. Text Surface Layer

The text surface layer analyzes the **formal shape of the text**, without semantic interpretation.

### Typical Features

```
character_count
word_count
sentence_count

line_length
line_length_ratio

capitalization_ratio

punctuation_density
digit_density

ends_with_period
ends_with_colon

starts_with_number
starts_with_bullet

contains_parentheses
contains_brackets

contains_url
contains_email
contains_doi
```

### Questions answered

This layer distinguishes between:

* narrative text
* labels
* captions
* references
* list entries
* TOC lines

Example patterns:

```
Short line + no punctuation → heading candidate
Many digits + parentheses → reference candidate
Dot leader pattern → TOC entry
```

---

# 8. Semantic Micro Layer

The semantic layer detects **lightweight semantic markers**.

This layer does not perform deep NLP but identifies key structural tokens.

### Typical Signals

```
contains "abstract"
contains "keywords"
contains "references"
contains "bibliography"
contains "appendix"

figure markers
table markers

year patterns

author patterns
institution patterns
```

### Questions answered

This layer identifies explicit structural indicators such as:

* abstract sections
* reference sections
* appendices
* figure captions

It is particularly useful for scientific articles.

---

# 9. Topology Layer

The topology layer analyzes **relationships between blocks**.

Blocks rarely appear in isolation; they form sequences and patterns.

### Typical Features

```
first_block_on_page
last_block_on_page

similarity_to_previous_block
similarity_to_next_block

series_length_same_style

distance_to_heading_candidate

page_header_candidate
page_footer_candidate
```

### Questions answered

Topology helps identify:

* repeating headers
* footers
* TOC lists
* reference lists
* figure caption groups
* heading-body transitions

Topology captures the **flow of the document**.

---

# 10. Context Layer

The context layer interprets blocks relative to the **global document structure**.

### Typical Context Signals

```
document_position_ratio

page_index_relative

zone_density_patterns

block_distribution_statistics
```

### Examples

```
Early pages → title / abstract / TOC more likely

Last pages → references more likely

Pages dominated by TOC patterns → TOC zone
```

Context is crucial for disambiguating blocks that look similar locally.

---

# 11. Structural Signal Layer

The structural signal layer aggregates all previous layers.

This layer produces **interpretable structural hypotheses**.

Examples:

```
title_like
heading_like
subheading_like

author_line_like

toc_like
reference_like
caption_like

body_like
noise_like
```

Signals are typically normalized scores in `[0,1]`.

These signals combine:

* geometry
* typography
* text surface
* semantics
* topology
* context

---

# 12. Role Inference

From signals the system derives **block roles**.

Examples:

```
title_line
section_heading
body_text

author_line

figure_caption
table_caption

toc_entry

reference_entry

noise
```

Role inference is a probabilistic interpretation of the signal layer.

---

# 13. Zone Reconstruction

Roles are aggregated into **semantic zones**.

Typical zones:

```
front_matter

abstract

body

figures

tables

references

toc
```

Zones represent contiguous regions of the document.

---

# 14. Section Tree Reconstruction

The final structural layer reconstructs the **document hierarchy**.

Example tree:

```
Title

Section
  Subsection
  Subsection

Section
  Subsection
```

Heading level inference uses:

```
numbering patterns
font hierarchy
whitespace hierarchy
typographic prominence
```

The resulting structure is stored as the **section tree**.

---

# 15. Pipeline Overview

The complete Atlas DU pipeline:

```
PDF
 │
 ▼
Block Extraction
 │
 ▼
Geometry Layer
 │
 ▼
Typography Layer
 │
 ▼
Text Surface Layer
 │
 ▼
Semantic Micro Layer
 │
 ▼
Topology Layer
 │
 ▼
Context Layer
 │
 ▼
Structural Signals
 │
 ▼
Block Roles
 │
 ▼
Semantic Zones
 │
 ▼
Section Tree
```

---

# 16. Design Principles

The architecture follows several core principles.

### Layer Independence

Each feature layer should be computed independently.

This prevents cascading errors.

### Interpretability

Signals should remain explainable.

The system should be inspectable via CLI tools.

### Robustness

Multiple weak signals combine into strong structural evidence.

### Document-Type Agnosticism

The architecture must support:

* journal articles
* essays
* books
* reports
* theses
* historical scans

---

# 17. Advantages of the Layered Model

The layered architecture provides several key benefits.

### Robustness to Layout Variation

Different documents emphasize different layers.

Example:

```
scientific articles → typography + semantics
historical essays → geometry + text surface
books → typography + topology
```

### Incremental Improvement

New detectors can be added without rewriting the entire system.

### Interpretability

Each decision can be traced back to its underlying signals.

### Extensibility

The system can later incorporate:

* machine learning classifiers
* layout vision models
* semantic embeddings

without breaking the architecture.

---

# 18. Summary

Atlas reconstructs document structure through **layered structural inference**.

Structure emerges from the interaction of multiple independent signals rather than from any single rule.

The architecture therefore treats document understanding as a **multi-layer evidence fusion problem**, allowing the system to operate robustly across a wide range of document types.

---

