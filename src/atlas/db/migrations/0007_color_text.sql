-- Migration 0007: text_color, color_rank, is_serif in du_block_typography,
-- plus color column in du_layout_lines and du_layout_spans.
--
-- text_color: raw RGB integer of the dominant span color (0x000000 = black).
-- color_rank: document-relative rank of the color by frequency.
--   0 = body color (most frequent in document, usually black)
--   1 = second most frequent (often heading brand color)
--   2+ = rare colors (links, highlights, ...)
-- is_serif: 1 if majority of block spans use a serifed typeface (flags & 4).
--
-- Analogous to font_percentile: document-agnostic, no hardcoded colors.

ALTER TABLE du_block_typography  ADD COLUMN text_color INTEGER DEFAULT 0;
ALTER TABLE du_block_typography  ADD COLUMN color_rank  INTEGER DEFAULT 0;
ALTER TABLE du_block_typography  ADD COLUMN is_serif    INTEGER DEFAULT 0;
ALTER TABLE du_layout_lines      ADD COLUMN color       INTEGER DEFAULT 0;
ALTER TABLE du_layout_spans      ADD COLUMN color       INTEGER DEFAULT 0;
