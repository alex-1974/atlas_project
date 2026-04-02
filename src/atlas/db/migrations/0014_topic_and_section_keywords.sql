-- db/migrations/0014_topic_and_section_keywords.sql
-- Trennung von Topic (was ist das Dokument?) und Keywords (welche Terme?)
--
-- documents.topic:
--   Extractiver Topic-Satz, 1-3 Sätze.
--   Befüllt durch atlas enrich --topic
--   Quelle: Titel + erster informativer Body-Block + erste Überschriften
--
-- du_section_keywords:
--   Keywords pro Section aus du_section_tree.
--   Befüllt durch atlas enrich --section-keywords
--   Granularität: eine Zeile pro Section, YAKE auf den Blöcken dieser Section.

ALTER TABLE documents ADD COLUMN topic TEXT;

CREATE TABLE IF NOT EXISTS du_section_keywords (
    section_node_id  INTEGER NOT NULL
                     REFERENCES du_section_tree(section_node_id)
                     ON DELETE CASCADE,
    document_id      TEXT NOT NULL
                     REFERENCES documents(document_id)
                     ON DELETE CASCADE,
    keywords         TEXT NOT NULL,   -- JSON-Array von Strings
    keyword_method   TEXT,            -- 'yake' | 'keybert' | 'tfidf'
    extracted_at     TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (section_node_id)
);

CREATE INDEX IF NOT EXISTS idx_section_keywords_doc
    ON du_section_keywords(document_id);
