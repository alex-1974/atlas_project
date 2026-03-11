alter table documents add column if not exists file_hash text;
alter table documents add column if not exists file_path text;
alter table documents add column if not exists relative_path text;
alter table documents add column if not exists file_name text;
alter table documents add column if not exists file_size bigint;
alter table documents add column if not exists top_category text;
alter table documents add column if not exists is_review_bucket boolean not null default false;
alter table documents add column if not exists is_duplicate_bucket boolean not null default false;
alter table documents add column if not exists page_count integer;

create unique index if not exists idx_documents_file_hash_unique
on documents(file_hash);
