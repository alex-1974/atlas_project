create table if not exists du_layout_spans (
    layout_span_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    page_index integer not null,
    block_no integer not null,
    line_no integer not null,
    span_no integer not null,
    reading_order integer not null,
    text text not null,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    page_width real,
    page_height real,
    font_name text,
    font_size real,
    font_flags integer,
    is_bold boolean not null default false,
    is_italic boolean not null default false,
    created_at timestamptz not null default now()
);

create index if not exists idx_du_layout_spans_doc_page_order
    on du_layout_spans(document_id, page_index, reading_order);

create index if not exists idx_du_layout_spans_doc_page_block_line
    on du_layout_spans(document_id, page_index, block_no, line_no, span_no);


create table if not exists du_layout_lines (
    layout_line_id uuid primary key,
    document_id uuid not null references documents(document_id) on delete cascade,
    page_index integer not null,
    block_no integer not null,
    line_no integer not null,
    reading_order integer not null,
    text text not null,
    x0 real,
    y0 real,
    x1 real,
    y1 real,
    page_width real,
    page_height real,
    font_name text,
    font_size real,
    font_flags integer,
    is_bold boolean not null default false,
    is_italic boolean not null default false,
    created_at timestamptz not null default now()
);

create index if not exists idx_du_layout_lines_doc_page_order
    on du_layout_lines(document_id, page_index, reading_order);

create index if not exists idx_du_layout_lines_doc_page_block_line
    on du_layout_lines(document_id, page_index, block_no, line_no);


alter table text_segments
    add column if not exists x0 real,
    add column if not exists y0 real,
    add column if not exists x1 real,
    add column if not exists y1 real,
    add column if not exists page_width real,
    add column if not exists page_height real;

create index if not exists idx_text_segments_doc_type_page
    on text_segments(document_id, segment_type, page_index, segment_index);
