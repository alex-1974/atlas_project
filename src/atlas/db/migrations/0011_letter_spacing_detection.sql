-- Migration 0011: letter-spacing detection
--
-- char_spacing: mean character gap relative to font size, computed from
-- chars[i]["origin"][0] deltas in PyMuPDF rawdict. Values > 0.85 indicate
-- letter-spaced text (Fall A — font attribute).
--
-- is_letter_spaced: 1 if the block is letter-spaced, detected via either:
--   Fall A: char_spacing > threshold in du_layout_spans
--   Fall B: text pattern 'T H E ...' (spaced single characters) in surface.py
-- Stored in du_block_typography alongside bold, italic, small_caps, all_caps.

ALTER TABLE du_layout_spans
    ADD COLUMN char_spacing REAL DEFAULT 0.0;

ALTER TABLE du_block_typography
    ADD COLUMN is_letter_spaced INTEGER DEFAULT 0;
