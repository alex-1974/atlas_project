create table if not exists document_regions (
    region_id bigserial primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    region_index integer not null,
    region_type text not null,
    start_char integer not null,
    end_char integer not null,
    text text not null,
    confidence double precision not null default 0.0,
    created_at timestamptz not null default now()
);

create index if not exists idx_document_regions_document_id
    on document_regions(document_id);

create index if not exists idx_document_regions_region_type
    on document_regions(region_type);

create unique index if not exists idx_document_regions_doc_region_index
    on document_regions(document_id, region_index);
