-- Atlas migration 0002: pipeline support tables
-- extracted_texts, extracted_metadata, document_identifiers

CREATE TABLE IF NOT EXISTS extracted_texts (
    document_id  TEXT PRIMARY KEY REFERENCES documents(document_id),
    text         TEXT NOT NULL,
    text_length  INTEGER,
    method       TEXT    -- pymupdf | pdftotext
);

CREATE TABLE IF NOT EXISTS extracted_metadata (
    document_id           TEXT PRIMARY KEY REFERENCES documents(document_id),
    method                TEXT,
    pdf_title             TEXT,
    pdf_author            TEXT,
    pdf_subject           TEXT,
    pdf_keywords          TEXT,
    pdf_creator           TEXT,
    pdf_producer          TEXT,
    pdf_creation_date_raw TEXT,
    pdf_mod_date_raw      TEXT
);

CREATE TABLE IF NOT EXISTS document_identifiers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id      TEXT    NOT NULL REFERENCES documents(document_id),
    identifier_type  TEXT    NOT NULL,  -- doi | isbn | arxiv_id | pmid | issn
    identifier_value TEXT    NOT NULL,
    source           TEXT,              -- text | pdf_metadata | filename
    UNIQUE(document_id, identifier_type, identifier_value, source)
);

CREATE INDEX IF NOT EXISTS idx_doc_identifiers_doc
    ON document_identifiers(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_identifiers_doi
    ON document_identifiers(identifier_type, identifier_value);
