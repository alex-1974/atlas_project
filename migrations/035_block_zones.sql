create table if not exists du_block_zones (
    block_id uuid primary key references du_blocks(block_id) on delete cascade,
    zone text not null,
    zone_confidence real,
    created_at timestamptz default now()
);
