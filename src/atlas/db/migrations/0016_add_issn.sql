-- Migration 0016: issn-Spalte in documents
-- ISSN war bisher nur in document_identifiers gespeichert.
-- Direkter Zugriff in documents erleichtert CrossRef-Abfragen
-- und FTS-Suche nach Zeitschriften-ISSN.

ALTER TABLE documents ADD COLUMN issn TEXT;

CREATE INDEX IF NOT EXISTS idx_documents_issn ON documents(issn);
