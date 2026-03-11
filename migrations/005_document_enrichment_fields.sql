alter table documents add column if not exists title text;
alter table documents add column if not exists title_source text;
alter table documents add column if not exists text_quality text;
alter table documents add column if not exists has_text_layer boolean;
alter table documents add column if not exists needs_ocr boolean not null default false;
alter table documents add column if not exists doc_state text;
