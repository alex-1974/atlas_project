-- Migration 0010: add contains_chapter_number to du_block_semantic_micro
--
-- contains_chapter_number: 1 if the block text begins with a numeric,
-- roman, or alphabetic chapter/section prefix (e.g. "1.1 INTRODUCTION",
-- "IV Results"). Used in signals.py to boost heading_like for numbered
-- section headings. Excludes TOC lines ("1.1 Introduction / 42") and
-- formula references ("Equation 3.4.3.1-2").

ALTER TABLE du_block_semantic_micro
    ADD COLUMN contains_chapter_number INTEGER DEFAULT 0;
