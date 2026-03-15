-- ============================================================
-- Atlas Document Understanding
-- Migration 007
-- Block Layout Features
-- ============================================================

create table if not exists du_block_layout_features (

    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    -- relative text size proxy
    size_ratio real,

    -- typography heuristics
    is_all_caps boolean,

    -- lexical structure
    word_count integer,
    ends_with_period boolean,

    -- structural patterns
    starts_with_number boolean,
    starts_with_bullet boolean,

    -- layout approximations
    line_width_ratio real,
    is_short_line boolean,

    created_at timestamptz default now()

);


-- ------------------------------------------------------------
-- indexes
-- ------------------------------------------------------------

create index if not exists idx_du_layout_word_count
    on du_block_layout_features(word_count);

create index if not exists idx_du_layout_caps
    on du_block_layout_features(is_all_caps);

create index if not exists idx_du_layout_short
    on du_block_layout_features(is_short_line);

create index if not exists idx_du_layout_numbered
    on du_block_layout_features(starts_with_number);


-- ------------------------------------------------------------
-- comments
-- ------------------------------------------------------------

comment on table du_block_layout_features is
'Language-independent layout features derived from block text';

comment on column du_block_layout_features.size_ratio is
'Relative block size proxy compared to document median';

comment on column du_block_layout_features.is_all_caps is
'True if block text is fully uppercase';

comment on column du_block_layout_features.word_count is
'Token count in block';

comment on column du_block_layout_features.line_width_ratio is
'Approximate line width normalized to typical text width';
