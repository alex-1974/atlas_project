-- db/migrations/0012_phase2_enrichment.sql
-- Phase 2: Anreicherungs-Infrastruktur
--
-- Neu:
--   documents.keywords        — JSON-Array extrahierter Schlagwörter
--   documents.language        — Primärsprache des Dokuments (ISO 639-1)
--   document_identifiers      — externe Identifier (RVK, GND, ORCID, ...)
--
-- Hinweis: language war früher schon in documents definiert (Phase 1),
-- wird hier als COALESCE-Update ergänzt falls noch nicht vorhanden.

-- Keywords-Spalte (JSON-Array)
ALTER TABLE documents ADD COLUMN keywords TEXT;

-- document_identifiers: beliebige externe Identifier pro Dokument
-- Typ-Beispiele: 'rvk', 'gnd', 'orcid', 'wikidata_qid', 'issn'
CREATE TABLE IF NOT EXISTS document_identifiers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id      TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    identifier_type  TEXT NOT NULL,   -- 'rvk' | 'gnd' | 'wikidata_qid' | ...
    identifier_value TEXT NOT NULL,
    source           TEXT,            -- 'local' | 'wikidata' | 'crossref' | 'rvk_api'
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(document_id, identifier_type, identifier_value)
);

CREATE INDEX IF NOT EXISTS idx_doc_identifiers_doc
    ON document_identifiers(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_identifiers_type_val
    ON document_identifiers(identifier_type, identifier_value);
