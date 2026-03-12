create table if not exists du_blocks (
    block_id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references documents(document_id)
        on delete cascade,

    page_index integer,
    block_index integer not null,

    start_char integer,
    end_char integer,
    text text not null,

    x0 real,
    y0 real,
    x1 real,
    y1 real,

    page_y0 real,
    page_y1 real,
    doc_y0 real,
    doc_y1 real,

    text_source text,
    geometry_source text,

    text_confidence real,
    geometry_confidence real,
    reading_order_confidence real,

    created_at timestamptz default now(),

    unique (document_id, block_index)
);
