# Atlas — Datenbank

## Übersicht

Atlas nutzt drei Speichersysteme mit komplementären Stärken:

| System | Datei | Zweck |
|---|---|---|
| SQLite | `.atlas/catalog.db` | Strukturierte Daten, Volltext, DU-Ergebnisse |
| Oxigraph | `.atlas/knowledge/` | RDF-Wissensgraph, Beziehungen |
| LanceDB | `.atlas/embeddings/` | Vektoren für semantische Suche |

Dieses Dokument beschreibt das SQLite-Schema.
Oxigraph: → [`ARCHITECTURE-KNOWLEDGE-GRAPH.md`](./ARCHITECTURE-KNOWLEDGE-GRAPH.md)

---

## SQLite-Konfiguration

```python
conn = sqlite3.connect(".atlas/catalog.db")
conn.execute("PRAGMA journal_mode = WAL")     # concurrent reads
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA synchronous = NORMAL")
```

UUIDs werden als `TEXT` gespeichert. Timestamps als ISO-8601-String
(`datetime('now')` für SQLite-Kompatibilität). Booleans als `INTEGER`
(0/1). Keine PostgreSQL-spezifischen Typen.

---

## Schema: Kerntabellen

### documents

Zentrale Dokument-Tabelle. Jedes Dokument hat genau einen Eintrag.

```sql
CREATE TABLE documents (
    document_id    TEXT PRIMARY KEY,        -- SHA-256 des Dateiinhalts
    file_path      TEXT NOT NULL UNIQUE,    -- absoluter Pfad
    file_name      TEXT,
    file_size      INTEGER,
    added_at       TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now')),

    -- Verarbeitungsstatus
    pipeline_status     TEXT DEFAULT 'pending',
                        -- pending | extracting | extracted |
                        -- du_processing | du_done | enriching |
                        -- indexed | failed
    du_document_type    TEXT,               -- aus DU-Pipeline
    pipeline_error      TEXT,               -- Fehlermeldung bei failed

    -- Metadaten (best-effort, aus Extraktion + Anreicherung)
    title          TEXT,
    authors        TEXT,                    -- JSON-Array
    year           INTEGER,
    abstract       TEXT,
    doi            TEXT,
    arxiv_id       TEXT,
    isbn           TEXT,
    pmid           TEXT,
    journal        TEXT,
    volume         TEXT,
    issue          TEXT,
    pages          TEXT,
    publisher      TEXT,
    language       TEXT,

    -- Erschließung (Phase 2, aus atlas enrich)
    keywords       TEXT,                    -- JSON-Array, YAKE/KeyBERT
                                            -- Input: Titel + Abstract + Seiten 0-2
    topic          TEXT,                    -- dominantes Konzept, GND-normalisiert
                                            -- Pipeline: GND-IDs → lobid preferred label
                                            -- Fallback: bestes Keyword mit Titelübereinstimmung
    subjects       TEXT,                    -- JSON-Array, Themen/RVK-Labels

    -- Qualität
    metadata_confidence REAL,
    has_native_text INTEGER DEFAULT 1
);

CREATE INDEX idx_documents_doi     ON documents(doi);
CREATE INDEX idx_documents_year    ON documents(year);
CREATE INDEX idx_documents_status  ON documents(pipeline_status);
```

**Unterschied keywords / topic / subjects:**

| Spalte | Granularität | Quelle | Verwendung |
|---|---|---|---|
| `keywords` | 10–20 Terme | YAKE auf Titel + Abstract + Einleitung | Suche, Tag-Cloud, Export |
| `topic` | 1 Konzept | GND preferred label (lobid.org) → Keyword-Fallback | RVK-Klassifikation, GND-Mapping |
| `subjects` | 3–8 Themen | RVK-Labels, Wikidata main_subject, Keyword-Fallback | Thematische Navigation |

### document_identifiers

Externe Identifier — mehrere pro Dokument möglich.

```sql
CREATE TABLE document_identifiers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id      TEXT NOT NULL REFERENCES documents(document_id)
                     ON DELETE CASCADE,
    identifier_type  TEXT NOT NULL,
                     -- doi | arxiv_id | isbn | pmid | issn |
                     -- orcid | wikidata | rvk | gnd
    identifier_value TEXT NOT NULL,
    UNIQUE(document_id, identifier_type, identifier_value)
);

CREATE INDEX idx_doc_identifiers_doc  ON document_identifiers(document_id);
CREATE INDEX idx_doc_identifiers_type ON document_identifiers(identifier_type);
```

### documents_fts

Volltext-Index über Titel, Abstract und Fließtext.

```sql
CREATE VIRTUAL TABLE documents_fts USING fts5(
    document_id UNINDEXED,
    title,
    abstract,
    body_text,
    content='documents',
    content_rowid='rowid'
);
```

---

## Schema: DU-Tabellen

### Basistabellen

```sql
CREATE TABLE du_documents (
    document_id     TEXT PRIMARY KEY REFERENCES documents(document_id),
    source_kind     TEXT,   -- born_digital_pdf | image_pdf | hybrid_pdf
    text_source     TEXT,   -- pdf_native | ocr | mixed
    geometry_source TEXT,
    has_native_text INTEGER,
    has_reliable_geometry INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE du_pages (
    page_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    page_index      INTEGER NOT NULL,
    width           REAL,
    height          REAL,
    UNIQUE(document_id, page_index)
);

CREATE TABLE du_blocks (
    block_id        TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    block_index     INTEGER NOT NULL,
    page_index      INTEGER NOT NULL,
    text            TEXT,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    doc_y0 REAL, doc_y1 REAL,   -- von geometry.py zurückgeschrieben
    text_source     TEXT,
    geometry_source TEXT,
    UNIQUE(document_id, block_index)
);

CREATE INDEX idx_du_blocks_document ON du_blocks(document_id, block_index);
```

### Schicht 1: Messtabellen

```sql
CREATE TABLE du_block_geometry (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    width REAL, height REAL,
    center_x REAL, center_y REAL,
    whitespace_before REAL, whitespace_after REAL,
    indent_left REAL, indent_right REAL,
    centeredness REAL,
    near_page_top REAL, near_page_bottom REAL,
    width_ratio REAL, height_ratio REAL,
    page_y_ratio REAL, doc_y_ratio REAL,
    left_margin REAL, right_margin REAL,
    full_width_like INTEGER,
    narrow_width_like INTEGER
    -- Hinweis: column_hint bewusst weggelassen bis Spaltenerkennung implementiert
);

CREATE TABLE du_block_typography (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    font_name TEXT, font_family TEXT, font_family_normalized TEXT,
    font_size REAL, font_ratio REAL,
    bold INTEGER, italic INTEGER,
    small_caps INTEGER, all_caps INTEGER,
    largest_on_page INTEGER,
    larger_than_prev INTEGER, larger_than_next INTEGER,
    font_size_delta_prev REAL, font_size_delta_next REAL,
    is_document_font_mode INTEGER,
    dominant_font_share REAL
);

CREATE TABLE du_block_surface (
    -- konsolidiert aus surface.py und typography_surface.py
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    char_count INTEGER, word_count INTEGER,
    sentence_count INTEGER, line_count INTEGER,
    mean_line_length REAL, line_width_ratio REAL, size_ratio REAL,
    capitalization_ratio REAL, punctuation_density REAL, digit_density REAL,
    is_all_caps INTEGER, is_short_line INTEGER,
    ends_with_period INTEGER, ends_with_colon INTEGER,
    starts_with_number INTEGER, starts_with_bullet INTEGER,
    contains_parentheses INTEGER, contains_brackets INTEGER,
    contains_url INTEGER, contains_email INTEGER,
    contains_doi INTEGER, contains_year INTEGER
);

CREATE TABLE du_block_spacing (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    line_gap_before REAL, line_gap_after REAL,
    paragraph_gap_before REAL, paragraph_gap_after REAL,
    indent_left REAL, indent_right REAL,
    alignment_left REAL, alignment_center REAL, alignment_right REAL,
    continuation_like REAL, break_like REAL
);

CREATE TABLE du_block_topology (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    same_page_prev INTEGER, same_page_next INTEGER,
    page_transition_before INTEGER, page_transition_after INTEGER,
    same_column_prev_like REAL, same_column_next_like REAL,
    odd_even_page TEXT,
    early_on_page_score REAL, late_on_page_score REAL
    -- repeated_header_footer_hint: wurde in du_block_furniture verschoben
);

CREATE TABLE du_block_furniture (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    is_top_band INTEGER, is_bottom_band INTEGER,
    page_number_like INTEGER,
    running_header_like INTEGER, running_footer_like INTEGER,
    repeated_across_pages INTEGER, repeated_same_parity INTEGER,
    first_page_meta_like INTEGER,
    repeated_hint INTEGER
);

CREATE TABLE du_block_context (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    doc_y_ratio REAL, page_y_ratio REAL,
    front_matter_score REAL,
    body_score REAL,
    back_matter_score REAL
    -- Hinweis: rein positionell, kein Rollenwissen
);

CREATE TABLE du_block_semantic_micro (
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    is_abstract_marker INTEGER, is_keywords_marker INTEGER,
    is_references_marker INTEGER, is_figure_marker INTEGER,
    is_table_marker INTEGER, is_appendix_marker INTEGER,
    contains_doi INTEGER, contains_year INTEGER,
    contains_citation_bracket INTEGER, contains_citation_author_year INTEGER
);
```

### Schicht 2: Aggregation

```sql
CREATE TABLE du_block_signals (
    block_id        TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    title_like      REAL DEFAULT 0.0,
    heading_like    REAL DEFAULT 0.0,
    body_like       REAL DEFAULT 0.0,   -- Achtung: früher irrtümlich
                                         -- 'running_text_like' in DB
    author_like     REAL DEFAULT 0.0,
    reference_like  REAL DEFAULT 0.0,
    caption_like    REAL DEFAULT 0.0,
    noise_like      REAL DEFAULT 0.0
);
```

### Schicht 3: Interpretation

```sql
CREATE TABLE du_block_roles (
    block_id        TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    role            TEXT NOT NULL,
    -- Mögliche Werte (aus vocab.Role):
    -- title | author | heading | body | reference |
    -- caption | noise | page_furniture | front_matter
    title_score     REAL, heading_score REAL, body_score REAL,
    author_score    REAL, reference_score REAL,
    caption_score   REAL, noise_score REAL
);

CREATE INDEX idx_du_block_roles_role ON du_block_roles(role);

CREATE TABLE du_heading_candidates (
    block_id        TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    block_index     INTEGER,
    page_index      INTEGER,
    text            TEXT,
    font_size       REAL, italic INTEGER,
    heading_score   REAL, body_score REAL,
    source          TEXT
);

CREATE TABLE du_block_zones (
    block_id        TEXT PRIMARY KEY REFERENCES du_blocks(block_id),
    zone            TEXT NOT NULL,
    -- Mögliche Werte (aus vocab.Zone):
    -- title_page | abstract | toc | body | references |
    -- appendix | front_matter | back_matter
    zone_confidence REAL,
    memberships     TEXT   -- JSON: {zone: score, ...} für Debugging
);

CREATE TABLE du_section_tree (
    section_node_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id             TEXT NOT NULL REFERENCES documents(document_id),
    parent_section_node_id  INTEGER REFERENCES du_section_tree(section_node_id),
    heading_block_id        TEXT REFERENCES du_blocks(block_id),
    start_block_index       INTEGER,
    end_block_index         INTEGER,
    page_start INTEGER, page_end INTEGER,
    level                   INTEGER,        -- 1 = H1, 2 = H2, ...
    title                   TEXT,
    title_normalized        TEXT,
    source                  TEXT            -- Versionierungsstring
);

CREATE INDEX idx_du_section_tree_doc ON du_section_tree(document_id, level);

-- Keywords pro Section (Migration 0014)
CREATE TABLE du_section_keywords (
    section_node_id  INTEGER NOT NULL
                     REFERENCES du_section_tree(section_node_id)
                     ON DELETE CASCADE,
    document_id      TEXT NOT NULL
                     REFERENCES documents(document_id)
                     ON DELETE CASCADE,
    keywords         TEXT NOT NULL,   -- JSON-Array von Strings
    keyword_method   TEXT,            -- 'yake' | 'keybert' | 'tfidf'
    extracted_at     TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (section_node_id)
);

CREATE INDEX idx_section_keywords_doc ON du_section_keywords(document_id);
```

---

## Volltext-Index (FTS5)

```sql
-- Volltext-Suche über Dokumentinhalte
CREATE VIRTUAL TABLE documents_fts USING fts5(
    document_id UNINDEXED,
    title,
    abstract,
    body_text,
    tokenize = 'unicode61 remove_diacritics 1'
);

-- Suche
SELECT document_id, rank
FROM documents_fts
WHERE documents_fts MATCH 'transformer attention mechanism'
ORDER BY rank;
```

---

## Migrations-Strategie

### Prinzip

Jede Schema-Änderung ist eine nummerierte Migration. Der Migration-Runner
in `db/migrate.py` führt alle ausstehenden Migrationen in Reihenfolge aus.
Das aktuelle Schema wird in der Tabelle `schema_migrations` protokolliert.

```python
# db/migrate.py
def run_migrations(conn: sqlite3.Connection) -> None:
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)
    for migration in _load_migrations():           # aus db/migrations/*.sql
        if migration.version not in applied:
            conn.executescript(migration.sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)",
                         (migration.version,))
            conn.commit()
```

### Migrations-Verzeichnis (aktueller Stand)

```
db/migrations/
├── 0001_initial.sql                    ← Basistabellen
├── 0002_pipeline_tables.sql
├── 0003_section_tree_drop_fk.sql
├── 0004_document_type_scores.sql
├── 0005_adds_font_percentile.sql
├── 0006_image_proximity.sql
├── 0007_color_text.sql
├── 0008_colored_box.sql
├── 0009_in_flow_score.sql
├── 0010_add_chapter_number.sql
├── 0011_letter_spacing_detection.sql
├── 0012_phase2_enrichment.sql          ← keywords, document_identifiers
├── 0013_subjects.sql                   ← subjects
└── 0014_topic_and_section_keywords.sql ← topic, du_section_keywords
```

### Wichtige Migration: body_like

Die Spalte wurde in Phase 1 von `running_text_like` umbenannt:

```sql
ALTER TABLE du_block_signals
RENAME COLUMN running_text_like TO body_like;
```

---

## Erschließungs-Pipeline

Keywords, Topic und Subjects werden nicht automatisch beim `atlas add`
befüllt — sie erfordern `atlas enrich`:

```bash
atlas enrich --keywords          # YAKE auf Titel + Abstract + Einleitung
atlas enrich --topic             # GND-normalisiertes Hauptkonzept
atlas enrich --section-keywords  # YAKE pro Section aus du_section_tree
atlas enrich --themes            # Subjects via RVK-API
atlas enrich --gnd               # GND-Identifier via lobid.org
atlas enrich --rvk               # RVK-Notation via rvk.uni-regensburg.de
atlas enrich --wikidata          # Wikidata QID via owl:sameAs
atlas enrich --crossref          # Vollständige Metadaten via DOI
```

**Abhängigkeiten:**

```
atlas enrich --gnd          (braucht: keywords)
atlas enrich --topic        (braucht: keywords + gnd)
atlas enrich --rvk          (braucht: keywords)
atlas enrich --themes       (braucht: rvk oder wikidata)
```

---

## Tabellen-Übersicht

| Tabelle | Schicht | Beschreibung |
|---|---|---|
| `documents` | Kern | Alle Dokumente, Metadaten, Status, Erschließung |
| `document_identifiers` | Kern | Externe Identifier (DOI, GND, RVK, ORCID, …) |
| `documents_fts` | Kern | FTS5-Volltext-Index |
| `du_documents` | DU-Basis | Dokumentkontext |
| `du_pages` | DU-Basis | Seiten |
| `du_blocks` | DU-Basis | Blöcke (atomare Einheit) |
| `du_block_geometry` | Messung | Räumliche Merkmale |
| `du_block_typography` | Messung | Font, Größe, Gewicht |
| `du_block_surface` | Messung | Textmerkmale |
| `du_block_spacing` | Messung | Abstände, Einzüge |
| `du_block_topology` | Messung | Seiten-Nachbarschaft |
| `du_block_furniture` | Messung | Header/Footer-Signale |
| `du_block_context` | Messung | Positionelle Phase-Scores |
| `du_block_semantic_micro` | Messung | Regex-Marker |
| `du_block_signals` | Aggregation | Kombinierte Scores |
| `du_block_roles` | Interpretation | Diskrete Rollen |
| `du_heading_candidates` | Interpretation | Heading-Kandidaten |
| `du_block_zones` | Interpretation | Semantische Zonen |
| `du_section_tree` | Interpretation | Hierarchische Struktur |
| `du_section_keywords` | Erschließung | Keywords pro Section (YAKE) |
