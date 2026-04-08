-- Migration 0015: du_heading_patterns
-- HeadingPatterns derived from high-confidence anchors (Phase 3 DU rewrite)

CREATE TABLE IF NOT EXISTS du_heading_patterns (
    pattern_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(document_id)
                    ON DELETE CASCADE,
    level           INTEGER NOT NULL,
    font_ratio_min  REAL,
    font_ratio_max  REAL,
    bold            INTEGER,          -- 0/1/NULL (NULL = accept both)
    all_caps        INTEGER,          -- 0/1/NULL
    gap_rel_min     REAL,             -- whitespace_before / gap_norm minimum
    flow_max        REAL,             -- maximum in_flow_score
    number_re       TEXT,             -- numbering regex or NULL
    confidence      REAL,             -- fraction of Tier-2 anchors (0–1)
    anchor_count    INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_heading_patterns_doc
    ON du_heading_patterns(document_id, level);
