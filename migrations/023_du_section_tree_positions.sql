-- migrations/023_du_section_tree.sql

drop table if exists du_section_tree cascade;

create table du_section_tree (
    document_id uuid not null
        references documents(document_id)
        on delete cascade,

    section_node_id integer not null,
    parent_section_node_id integer,

    heading_block_id uuid
        references du_blocks(block_id)
        on delete set null,

    start_block_index integer not null,
    end_block_index integer not null,

    page_start integer,
    page_end integer,

    level integer not null,
    role text not null default 'heading',

    section_number text,
    title text not null,
    title_normalized text,

    is_numbered boolean not null default false,
    confidence real,
    source text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    primary key (document_id, section_node_id),

    constraint du_section_tree_parent_fk
        foreign key (document_id, parent_section_node_id)
        references du_section_tree(document_id, section_node_id)
        on delete cascade,

    constraint du_section_tree_block_range_chk
        check (start_block_index <= end_block_index),

    constraint du_section_tree_page_range_chk
        check (
            page_start is null
            or page_end is null
            or page_start <= page_end
        ),

    constraint du_section_tree_level_chk
        check (level >= 1)
);

create index idx_du_section_tree_doc
    on du_section_tree(document_id);

create index idx_du_section_tree_doc_parent
    on du_section_tree(document_id, parent_section_node_id);

create index idx_du_section_tree_doc_level
    on du_section_tree(document_id, level);

create index idx_du_section_tree_doc_start
    on du_section_tree(document_id, start_block_index);

create index idx_du_section_tree_doc_end
    on du_section_tree(document_id, end_block_index);

create index idx_du_section_tree_doc_pages
    on du_section_tree(document_id, page_start, page_end);

create unique index uq_du_section_tree_doc_heading_block
    on du_section_tree(document_id, heading_block_id)
    where heading_block_id is not null;
