-- 034_du_document_model_and_heading_candidates.sql

create table if not exists du_document_model (
    document_id uuid primary key
        references documents(document_id)
        on delete cascade,
    body_font_family text,
    body_font_size real,
    style_clusters jsonb,
    heading_style_candidates jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists du_heading_candidates (
    heading_id uuid primary key default gen_random_uuid(),
    document_id uuid not null
        references documents(document_id)
        on delete cascade,
    block_id uuid not null
        references du_blocks(block_id)
        on delete cascade,
    heading_score real,
    level integer,
    is_title boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_du_heading_doc
    on du_heading_candidates(document_id);

create index if not exists idx_du_heading_doc_block
    on du_heading_candidates(document_id, block_id);
