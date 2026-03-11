create table if not exists document_identifiers (
    identifier_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    identifier_type text not null,
    identifier_value text not null,
    source text not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_document_identifiers_document_id
on document_identifiers(document_id);

create index if not exists idx_document_identifiers_type
on document_identifiers(identifier_type);

create unique index if not exists idx_document_identifiers_unique
on document_identifiers(document_id, identifier_type, identifier_value);
