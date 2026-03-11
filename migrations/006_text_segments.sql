create table if not exists text_segments (
    segment_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    segment_index integer not null,
    segment_type text not null,
    text text not null,
    char_length integer,
    created_at timestamptz not null default now()
);

create index if not exists idx_text_segments_document_id
on text_segments(document_id);

create index if not exists idx_text_segments_segment_type
on text_segments(segment_type);
