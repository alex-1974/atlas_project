alter table text_segments
    add column if not exists page_index integer;

create index if not exists idx_text_segments_document_page
    on text_segments(document_id, page_index, segment_index);
