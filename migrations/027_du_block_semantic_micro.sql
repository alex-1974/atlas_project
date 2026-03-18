create table if not exists du_block_semantic_micro (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    is_abstract_marker boolean,
    is_keywords_marker boolean,
    is_references_marker boolean,
    is_figure_marker boolean,
    is_table_marker boolean,
    is_appendix_marker boolean,

    contains_doi boolean,
    contains_year boolean,
    contains_citation_bracket boolean,
    contains_citation_author_year boolean,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
