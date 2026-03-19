alter table du_block_geometry
    add column if not exists width_ratio real,
    add column if not exists height_ratio real,
    add column if not exists page_y_ratio real,
    add column if not exists doc_y_ratio real,
    add column if not exists left_margin real,
    add column if not exists right_margin real,
    add column if not exists full_width_like boolean not null default false,
    add column if not exists narrow_width_like boolean not null default false;

alter table du_block_typography
    add column if not exists font_family_normalized text,
    add column if not exists dominant_font_share real,
    add column if not exists font_size_delta_prev real,
    add column if not exists font_size_delta_next real;

create table if not exists du_block_spacing_rhythm (
    block_id uuid primary key references du_blocks(block_id) on delete cascade,
    line_gap_before real,
    line_gap_after real,
    paragraph_gap_before real,
    paragraph_gap_after real,
    indent_left real,
    indent_right real,
    alignment_left real,
    alignment_center real,
    alignment_right real,
    same_column_continuation_like real,
    new_region_break_like real,
    updated_at timestamptz not null default now()
);

create table if not exists du_block_topology_signals (
    block_id uuid primary key references du_blocks(block_id) on delete cascade,
    same_page_prev boolean not null default false,
    same_page_next boolean not null default false,
    page_transition_before boolean not null default false,
    page_transition_after boolean not null default false,
    same_column_prev_like real,
    same_column_next_like real,
    column_index_candidate integer,
    odd_even_page text,
    early_on_page_score real,
    late_on_page_score real,
    updated_at timestamptz not null default now()
);

create table if not exists du_block_page_furniture_signals (
    block_id uuid primary key references du_blocks(block_id) on delete cascade,
    is_top_band boolean not null default false,
    is_bottom_band boolean not null default false,
    page_number_like boolean not null default false,
    running_header_like boolean not null default false,
    running_footer_like boolean not null default false,
    repeated_across_pages boolean not null default false,
    repeated_same_parity boolean not null default false,
    first_page_meta_like boolean not null default false,
    updated_at timestamptz not null default now()
);

create index if not exists idx_du_block_spacing_rhythm_updated_at
    on du_block_spacing_rhythm(updated_at);

create index if not exists idx_du_block_topology_signals_odd_even
    on du_block_topology_signals(odd_even_page);

create index if not exists idx_du_block_page_furniture_signals_flags
    on du_block_page_furniture_signals(
        is_top_band,
        is_bottom_band,
        running_header_like,
        running_footer_like
    );
