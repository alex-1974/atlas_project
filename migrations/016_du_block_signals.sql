create table if not exists du_block_signals (
    block_id uuid primary key
        references du_blocks(block_id)
        on delete cascade,

    title_like real,
    author_like real,
    affiliation_like real,
    date_like real,

    running_text_like real,
    heading_like real,
    list_like real,
    toc_like real,
    reference_like real,
    bibliographic_entry_like real,
    caption_like real,
    marker_like real,
    parenthetical_citation_like real,

    journal_meta_like real,
    artifact_like real,
    noise_like real,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
