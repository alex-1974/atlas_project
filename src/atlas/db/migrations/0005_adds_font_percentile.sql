-- Migration 0005: add font_percentile to du_block_typography
--
-- font_percentile: where does this block's font_size sit in the
-- document-wide distribution? 0.0 = smallest, 1.0 = largest.
-- Computed in typography.py second pass using sorted all_sizes.
-- Replaces font_ratio as the primary heading/title gate in signals.py
-- because it is document-agnostic: a 14pt title in a 9pt journal and
-- a 48pt title in an illustrated report both score near 1.0.

ALTER TABLE du_block_typography ADD COLUMN font_percentile REAL;
