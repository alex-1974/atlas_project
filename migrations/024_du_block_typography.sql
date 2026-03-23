create table if not exists du_block_typography (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    font_name text,
    font_family text,
    font_size real,
    font_ratio real,

    bold boolean,
    italic boolean,
    small_caps boolean,
    all_caps boolean,

    largest_on_page boolean,
    larger_than_prev boolean,
    larger_than_next boolean,

    font_name_change_prev boolean,
    font_name_change_next boolean,
    font_size_change_prev boolean,
    font_size_change_next boolean,

    is_document_font_mode boolean,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
