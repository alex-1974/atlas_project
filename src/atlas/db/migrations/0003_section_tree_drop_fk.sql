-- Atlas migration 0003
-- Remove FOREIGN KEY on du_section_tree.heading_block_id
--
-- Rationale: section tree nodes are logical structure elements.
-- heading_block_id is a soft reference for display purposes only.
-- The FK made the table fragile during re-processing (two-pass pipeline,
-- remove/re-add cycles) because SQLite cannot defer FK checks within
-- executemany and PRAGMA foreign_keys = OFF has no effect inside an
-- active WAL transaction.
--
-- SQLite cannot DROP a column constraint directly.
-- We use the recommended table-rebuild approach.

PRAGMA foreign_keys = OFF;

CREATE TABLE du_section_tree_new (
    section_node_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id             TEXT    NOT NULL REFERENCES documents(document_id),
    parent_section_node_id  INTEGER,        -- no FK: self-reference resolved in app
    heading_block_id        TEXT,           -- no FK: soft reference only
    start_block_index       INTEGER,
    end_block_index         INTEGER,
    page_start              INTEGER,
    page_end                INTEGER,
    level                   INTEGER,
    title                   TEXT,
    title_normalized        TEXT,
    source                  TEXT
);

INSERT INTO du_section_tree_new
    SELECT * FROM du_section_tree;

DROP TABLE du_section_tree;
ALTER TABLE du_section_tree_new RENAME TO du_section_tree;

CREATE INDEX IF NOT EXISTS idx_du_section_tree_doc
    ON du_section_tree (document_id, level);

PRAGMA foreign_keys = ON;
