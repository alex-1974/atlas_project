create table if not exists du_zone_hypotheses (
    zone_hypothesis_id uuid primary key default gen_random_uuid(),

    document_id uuid not null
        references documents(document_id)
        on delete cascade,

    zone_type text not null,
    start_block_index integer not null,
    end_block_index integer not null,

    page_start integer,
    page_end integer,

    score real not null,
    source text not null,

    created_at timestamptz default now()
);
