create table if not exists du_block_context (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    doc_y_ratio real,
    page_y_ratio real,

    front_matter_score real,
    body_score real,
    back_matter_score real,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
