-- Migration 0015: graph-corrected block scores (Schicht 2.5)
--
-- Adds optional graph_* columns to du_block_signals.
-- These are populated by understanding/graph/corrections.py after
-- the neighbourhood graph analysis (Layer 2.5).
-- Schicht 3 (roles.py) reads COALESCE(graph_title_like, title_like) etc.
-- so the original Layer-2 scores are always preserved for comparison.
--
-- NULL means "no graph correction applied" — the original score stands.

ALTER TABLE du_block_signals ADD COLUMN graph_title_like   REAL;
ALTER TABLE du_block_signals ADD COLUMN graph_heading_like REAL;
ALTER TABLE du_block_signals ADD COLUMN graph_body_like    REAL;
ALTER TABLE du_block_signals ADD COLUMN graph_author_like  REAL;
ALTER TABLE du_block_signals ADD COLUMN graph_noise_like   REAL;

-- Which correction rules fired for this block (JSON array of rule names).
-- Useful for atlas dev du inspect and debugging.
ALTER TABLE du_block_signals ADD COLUMN graph_rules_fired  TEXT;
