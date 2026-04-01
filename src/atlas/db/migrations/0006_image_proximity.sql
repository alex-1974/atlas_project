-- Migration 0006: image bounding boxes per page
--
-- Stores the bounding box of every raster/vector image block extracted
-- by PyMuPDF (rawdict type=1).  Used by geometry.py to compute
-- near_image_score for text blocks — the primary signal for detecting
-- figure captions that lack a "Figure N" prefix.

CREATE TABLE IF NOT EXISTS du_layout_images (
    image_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    page_index  INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL
);

CREATE INDEX IF NOT EXISTS idx_du_layout_images_doc
    ON du_layout_images(document_id, page_index);

-- Migration 0006b: near_image_score in du_block_geometry
ALTER TABLE du_block_geometry ADD COLUMN near_image_score REAL;
