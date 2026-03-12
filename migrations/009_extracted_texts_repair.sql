alter table extracted_texts
    add column if not exists text_length integer;

alter table extracted_texts
    add column if not exists nul_bytes_removed integer not null default 0;

alter table extracted_texts
    add column if not exists extract_status text not null default 'ok';

alter table extracted_texts
    add column if not exists extract_error text;
