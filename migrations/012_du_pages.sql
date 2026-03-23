create table if not exists du_pages (
    page_id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references documents(document_id)
        on delete cascade,

    page_index integer not null,
    width real,
    height real,

    image_based boolean,
    native_text_present boolean,
    page_confidence real,

    created_at timestamptz default now(),

    unique (document_id, page_index)
);
