create table if not exists pdf_metadata (
    metadata_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    title text,
    author text,
    subject text,
    keywords text,
    creator text,
    producer text,
    creation_date text,
    mod_date text,
    raw_json jsonb,
    created_at timestamptz not null default now()
);
