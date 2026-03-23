create table if not exists du_block_zone_memberships (
    block_id uuid not null
        references du_blocks(block_id)
        on delete cascade,

    zone_type text not null,
    membership real not null,

    source text not null,
    created_at timestamptz default now(),

    primary key (block_id, zone_type, source)
);
