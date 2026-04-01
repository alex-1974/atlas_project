-- db/migrations/0013_subjects.sql
-- Themen/Subjects-Spalte für übergeordnete Konzepte
-- Wird befüllt durch atlas enrich --themes
-- JSON-Array von Strings, z.B. ["Historische Bauforschung", "Stadtmorphologie"]

ALTER TABLE documents ADD COLUMN subjects TEXT;
