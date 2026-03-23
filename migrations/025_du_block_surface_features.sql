create table if not exists du_block_surface_features (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    char_count integer,
    word_count integer,
    sentence_count integer,
    line_count integer,
    mean_line_length real,

    line_width_ratio real,
    capitalization_ratio real,
    punctuation_density real,
    digit_density real,

    ends_with_period boolean,
    ends_with_colon boolean,
    starts_with_number boolean,
    starts_with_bullet boolean,

    contains_parentheses boolean,
    contains_brackets boolean,
    contains_url boolean,
    contains_email boolean,
    contains_doi boolean,
    contains_year boolean,

    is_all_caps boolean,
    is_short_line boolean,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
