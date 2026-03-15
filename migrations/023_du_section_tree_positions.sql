-- ============================================================
-- Atlas Document Understanding
-- Migration 023
-- Section tree positions
-- ============================================================

alter table du_section_tree
    add column if not exists start_block_index integer,
    add column if not exists end_block_index integer,
    add column if not exists page_start integer,
    add column if not exists page_end integer;

create index if not exists idx_du_section_tree_document_start_block
    on du_section_tree(document_id, start_block_index);

create index if not exists idx_du_section_tree_document_page_start
    on du_section_tree(document_id, page_start);

comment on column du_section_tree.start_block_index is
'First block_index covered by the section node';

comment on column du_section_tree.end_block_index is
'Last block_index covered by the section node';

comment on column du_section_tree.page_start is
'First page_index covered by the section node';

comment on column du_section_tree.page_end is
'Last page_index covered by the section node';
