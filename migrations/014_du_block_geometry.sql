create table if not exists du_block_geometry (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    width real,
    height real,
    center_x real,
    center_y real,

    whitespace_before real,
    whitespace_after real,

    indent_left real,
    indent_right real,
    centeredness real,
    column_hint real,

    near_page_top real,
    near_page_bottom real,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
