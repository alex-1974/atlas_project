-- Atlas migration 0004
-- Add du_document_type_scores column to documents table.
-- Stores a JSON probability vector: {"article": 0.65, "archival": 0.35}
-- du_document_type remains the primary type (highest probability).

ALTER TABLE documents ADD COLUMN du_document_type_scores TEXT;
