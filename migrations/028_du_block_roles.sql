create table if not exists du_block_roles (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    role text not null,

    title_score real,
    heading_score real,
    body_score real,
    reference_score real,
    caption_score real,
    noise_score real,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
