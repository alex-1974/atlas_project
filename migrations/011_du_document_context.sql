create table if not exists du_document_context (
    document_id uuid primary key
        references documents(document_id)
        on delete cascade,

    source_kind text not null,
    text_source text not null,
    geometry_source text not null,
    reading_order_source text not null,

    has_native_text boolean not null default false,
    has_reliable_geometry boolean not null default false,
    has_reliable_reading_order boolean not null default false,

    text_confidence real,
    geometry_confidence real,
    reading_order_confidence real,

    notes text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
