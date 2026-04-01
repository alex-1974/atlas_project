-- Migration 0009: in_flow_score in du_block_spacing.
--
-- in_flow_score: 1.0 = block is part of the normal vertical text flow.
-- 0.0 = block is spatially scattered (map label, legend, sidebar item).
--
-- Computed from whitespace_before relative to the positive-only median
-- of all inter-block gaps in the document.  Negative whitespace_before
-- (block overlaps previous in reading order) → 0.0.  Normal flow range
-- (0.1–5× the median gap) → 0.2–1.0.
--
-- Used in signals.py to gate heading_like: a block that is not in the
-- normal text flow should not become a section heading even if it has
-- bold text or a heading-size font.

ALTER TABLE du_block_spacing ADD COLUMN in_flow_score REAL DEFAULT 0.5;
