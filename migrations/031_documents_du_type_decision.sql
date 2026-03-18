alter table documents
    add column if not exists du_document_type_secondary text;

alter table documents
    add column if not exists du_document_type_margin real;

alter table documents
    add column if not exists du_document_type_confidence real;

alter table documents
    add column if not exists du_document_type_ambiguous boolean not null default false;
