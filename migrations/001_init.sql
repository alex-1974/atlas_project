create extension if not exists pgcrypto;

create table if not exists documents (
    document_id uuid primary key,
    file_hash text unique not null,
    file_path text not null,
    relative_path text not null,
    file_name text not null,
    file_size bigint,
    top_category text,
    is_review_bucket boolean not null default false,
    is_duplicate_bucket boolean not null default false,
    page_count integer,
    created_at timestamptz not null default now()
);
