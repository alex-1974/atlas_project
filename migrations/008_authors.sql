create table if not exists authors (
    author_id uuid primary key,
    display_name text not null,
    normalized_name text not null,
    created_at timestamptz not null default now()
);

create unique index if not exists idx_authors_normalized_name_unique
on authors(normalized_name);

create table if not exists document_authors (
    document_author_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    author_id uuid not null references authors(author_id) on delete cascade,
    author_position integer,
    source text not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_document_authors_document_id
on document_authors(document_id);

create index if not exists idx_document_authors_author_id
on document_authors(author_id);

create unique index if not exists idx_document_authors_unique
on document_authors(document_id, author_id);
