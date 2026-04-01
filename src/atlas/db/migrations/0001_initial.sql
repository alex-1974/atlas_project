-- Atlas initial schema
-- Version: 0001
--
-- Bugfixes gegenüber dem alten System, die hier bereits eingebaut sind:
--   Bug 1: Spalte heißt body_like (nicht running_text_like)
--   Bug 3: du_block_furniture enthält repeated_hint (nicht du_block_topology)
--   Bug 5: du_block_topology enthält kein repeated_header_footer_hint mehr


-- ============================================================
-- Kerntabellen
-- ============================================================

CREATE TABLE IF NOT EXISTS documents (
    document_id          TEXT PRIMARY KEY,   -- SHA-256 des Dateiinhalts
    file_path            TEXT NOT NULL UNIQUE,
    file_name            TEXT,
    file_size            INTEGER,
    added_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),

    pipeline_status      TEXT NOT NULL DEFAULT 'pending',
    -- pending | extracting | extracted | du_processing | du_done
    -- | enriching | indexed | failed

    du_document_type     TEXT,
    pipeline_error       TEXT,

    title                TEXT,
    authors              TEXT,   -- JSON array of strings
    year                 INTEGER,
    abstract             TEXT,
    doi                  TEXT,
    arxiv_id             TEXT,
    isbn                 TEXT,
    pmid                 TEXT,
    journal              TEXT,
    volume               TEXT,
    issue                TEXT,
    pages                TEXT,
    publisher            TEXT,
    language             TEXT,

    metadata_confidence  REAL,
    has_native_text      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_documents_doi
    ON documents (doi);
CREATE INDEX IF NOT EXISTS idx_documents_year
    ON documents (year);
CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (pipeline_status);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5 (
    document_id  UNINDEXED,
    title,
    abstract,
    body_text,
    tokenize = 'unicode61 remove_diacritics 1'
);


-- ============================================================
-- DU — Basistabellen
-- ============================================================

CREATE TABLE IF NOT EXISTS du_documents (
    document_id          TEXT PRIMARY KEY
                             REFERENCES documents (document_id),
    source_kind          TEXT,   -- born_digital_pdf | image_pdf | hybrid_pdf
    text_source          TEXT,   -- pdf_native | ocr | mixed
    geometry_source      TEXT,
    has_native_text      INTEGER,
    has_reliable_geometry INTEGER,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS du_pages (
    page_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  TEXT    NOT NULL REFERENCES documents (document_id),
    page_index   INTEGER NOT NULL,
    width        REAL,
    height       REAL,
    UNIQUE (document_id, page_index)
);

CREATE TABLE IF NOT EXISTS du_blocks (
    block_id        TEXT    PRIMARY KEY,
    document_id     TEXT    NOT NULL REFERENCES documents (document_id),
    block_index     INTEGER NOT NULL,
    page_index      INTEGER NOT NULL,
    text            TEXT,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    doc_y0          REAL,   -- zurückgeschrieben von geometry.py
    doc_y1          REAL,
    text_source     TEXT,
    geometry_source TEXT,
    UNIQUE (document_id, block_index)
);

CREATE INDEX IF NOT EXISTS idx_du_blocks_document
    ON du_blocks (document_id, block_index);


-- ============================================================
-- Schicht 1 — Messung
-- ============================================================

CREATE TABLE IF NOT EXISTS du_block_geometry (
    block_id          TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    width             REAL,
    height            REAL,
    center_x          REAL,
    center_y          REAL,
    whitespace_before REAL,
    whitespace_after  REAL,
    indent_left       REAL,
    indent_right      REAL,
    centeredness      REAL,
    near_page_top     REAL,
    near_page_bottom  REAL,
    width_ratio       REAL,
    height_ratio      REAL,
    page_y_ratio      REAL,
    doc_y_ratio       REAL,
    left_margin       REAL,
    right_margin      REAL,
    full_width_like   INTEGER,
    narrow_width_like INTEGER
    -- column_hint absichtlich weggelassen bis Spaltenerkennung
    -- implementiert ist (OE-1, Phase 4)
);

CREATE TABLE IF NOT EXISTS du_block_typography (
    block_id                  TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    font_name                 TEXT,
    font_family               TEXT,
    font_family_normalized    TEXT,
    font_size                 REAL,
    font_ratio                REAL,
    bold                      INTEGER,
    italic                    INTEGER,
    small_caps                INTEGER,
    all_caps                  INTEGER,
    largest_on_page           INTEGER,
    larger_than_prev          INTEGER,
    larger_than_next          INTEGER,
    font_size_delta_prev      REAL,
    font_size_delta_next      REAL,
    is_document_font_mode     INTEGER,
    dominant_font_share       REAL
);

CREATE TABLE IF NOT EXISTS du_block_surface (
    -- konsolidiert aus surface.py und typography_surface.py
    block_id                TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    char_count              INTEGER,
    word_count              INTEGER,
    sentence_count          INTEGER,
    line_count              INTEGER,
    mean_line_length        REAL,
    line_width_ratio        REAL,
    size_ratio              REAL,
    capitalization_ratio    REAL,
    punctuation_density     REAL,
    digit_density           REAL,
    is_all_caps             INTEGER,
    is_short_line           INTEGER,
    ends_with_period        INTEGER,
    ends_with_colon         INTEGER,
    starts_with_number      INTEGER,
    starts_with_bullet      INTEGER,
    contains_parentheses    INTEGER,
    contains_brackets       INTEGER,
    contains_url            INTEGER,
    contains_email          INTEGER,
    contains_doi            INTEGER,
    contains_year           INTEGER
);

CREATE TABLE IF NOT EXISTS du_block_spacing (
    block_id               TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    line_gap_before        REAL,
    line_gap_after         REAL,
    paragraph_gap_before   REAL,
    paragraph_gap_after    REAL,
    indent_left            REAL,
    indent_right           REAL,
    alignment_left         REAL,
    alignment_center       REAL,
    alignment_right        REAL,
    continuation_like      REAL,
    break_like             REAL
);

CREATE TABLE IF NOT EXISTS du_block_topology (
    block_id                TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    same_page_prev          INTEGER,
    same_page_next          INTEGER,
    page_transition_before  INTEGER,
    page_transition_after   INTEGER,
    same_column_prev_like   REAL,
    same_column_next_like   REAL,
    odd_even_page           TEXT,
    early_on_page_score     REAL,
    late_on_page_score      REAL
    -- repeated_header_footer_hint hier bewusst entfernt
    -- es lebt jetzt in du_block_furniture.repeated_hint (Bug 3 Fix)
);

CREATE TABLE IF NOT EXISTS du_block_furniture (
    block_id              TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    is_top_band           INTEGER,
    is_bottom_band        INTEGER,
    page_number_like      INTEGER,
    running_header_like   INTEGER,
    running_footer_like   INTEGER,
    repeated_across_pages INTEGER,
    repeated_same_parity  INTEGER,
    first_page_meta_like  INTEGER,
    repeated_hint         INTEGER   -- hier, nicht in du_block_topology
);

CREATE TABLE IF NOT EXISTS du_block_context (
    -- rein positionell, kein Rollenwissen (Schicht-1-Invariante)
    block_id            TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    doc_y_ratio         REAL,
    page_y_ratio        REAL,
    front_matter_score  REAL,
    body_score          REAL,
    back_matter_score   REAL
);

CREATE TABLE IF NOT EXISTS du_block_semantic_micro (
    block_id                       TEXT PRIMARY KEY
                                       REFERENCES du_blocks (block_id),
    is_abstract_marker             INTEGER,
    is_keywords_marker             INTEGER,
    is_references_marker           INTEGER,
    is_figure_marker               INTEGER,
    is_table_marker                INTEGER,
    is_appendix_marker             INTEGER,
    contains_doi                   INTEGER,
    contains_year                  INTEGER,
    contains_citation_bracket      INTEGER,
    contains_citation_author_year  INTEGER
);


-- ============================================================
-- Schicht 2 — Aggregation
-- ============================================================

CREATE TABLE IF NOT EXISTS du_block_signals (
    block_id        TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    title_like      REAL NOT NULL DEFAULT 0.0,
    heading_like    REAL NOT NULL DEFAULT 0.0,
    body_like       REAL NOT NULL DEFAULT 0.0,   -- Bug 1 Fix: war running_text_like
    author_like     REAL NOT NULL DEFAULT 0.0,
    reference_like  REAL NOT NULL DEFAULT 0.0,
    caption_like    REAL NOT NULL DEFAULT 0.0,
    noise_like      REAL NOT NULL DEFAULT 0.0
);


-- ============================================================
-- Schicht 3 — Interpretation
-- ============================================================

CREATE TABLE IF NOT EXISTS du_block_roles (
    block_id         TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    role             TEXT NOT NULL,
    -- title | author | heading | body | reference |
    -- caption | noise | page_furniture | front_matter
    title_score      REAL,
    heading_score    REAL,
    body_score       REAL,
    author_score     REAL,
    reference_score  REAL,
    caption_score    REAL,
    noise_score      REAL
);

CREATE INDEX IF NOT EXISTS idx_du_block_roles_role
    ON du_block_roles (role);

CREATE TABLE IF NOT EXISTS du_heading_candidates (
    block_id        TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    block_index     INTEGER,
    page_index      INTEGER,
    text            TEXT,
    font_size       REAL,
    italic          INTEGER,
    heading_score   REAL,
    body_score      REAL,
    source          TEXT
);

CREATE TABLE IF NOT EXISTS du_block_zones (
    block_id         TEXT PRIMARY KEY REFERENCES du_blocks (block_id),
    zone             TEXT NOT NULL,
    -- title_page | abstract | toc | body | references |
    -- appendix | front_matter | back_matter
    zone_confidence  REAL,
    memberships      TEXT   -- JSON: {zone: score, ...} für Debugging
);

CREATE TABLE IF NOT EXISTS du_section_tree (
    section_node_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id             TEXT    NOT NULL
                                REFERENCES documents (document_id),
    parent_section_node_id  INTEGER
                                REFERENCES du_section_tree (section_node_id),
    heading_block_id        TEXT    REFERENCES du_blocks (block_id),
    start_block_index       INTEGER,
    end_block_index         INTEGER,
    page_start              INTEGER,
    page_end                INTEGER,
    level                   INTEGER,   -- 1 = H1, 2 = H2, ...
    title                   TEXT,
    title_normalized        TEXT,
    source                  TEXT
);

CREATE INDEX IF NOT EXISTS idx_du_section_tree_doc
    ON du_section_tree (document_id, level);
