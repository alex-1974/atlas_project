create table if not exists du_block_topology (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    prev_block_index integer,
    next_block_index integer,

    cluster_id integer,
    early_block_rank integer,

    is_first_on_page boolean not null default false,
    is_last_on_page boolean not null default false,

    before_first_running_text boolean not null default false,
    after_toc_candidate boolean not null default false,
    repeated_header_footer_hint boolean not null default false,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
