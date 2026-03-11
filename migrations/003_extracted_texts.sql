create table if not exists extracted_texts (
    extraction_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    extractor text not null,
    text_full text,
    text_length integer,
    nul_bytes_removed integer not null default 0,
    extract_status text not null default 'ok',
    extract_error text,
    created_at timestamptz not null default now()
);
