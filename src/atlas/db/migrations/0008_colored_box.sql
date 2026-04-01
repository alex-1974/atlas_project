-- Migration 0008: in_colored_box in du_block_geometry,
-- and du_layout_drawings table for background fill shapes.
--
-- in_colored_box: 1 if the block is contained within a colored background
-- fill (sidebar, callout, highlighted section).  Used in signals.py to
-- differentiate inline sidebars from section headings.
--
-- du_layout_drawings: stores non-white fill shapes extracted from
-- page.get_drawings() in PyMuPDF.  Used by geometry.py to compute
-- in_colored_box.

CREATE TABLE IF NOT EXISTS du_layout_drawings (
    drawing_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT    NOT NULL REFERENCES documents(document_id),
    page_index  INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    fill_r REAL, fill_g REAL, fill_b REAL
);

CREATE INDEX IF NOT EXISTS idx_du_layout_drawings_doc
    ON du_layout_drawings(document_id, page_index);

ALTER TABLE du_block_geometry ADD COLUMN in_colored_box INTEGER DEFAULT 0;
