alter table query_log add column if not exists client text;
alter table query_log add column if not exists cached boolean not null default false;

create index if not exists query_log_client_idx on query_log (client, at desc);

create table if not exists answer_cache (
    key        text primary key,
    question   text not null,
    payload    jsonb not null,
    at         timestamptz not null default now(),
    hits       int not null default 0
);

create index if not exists answer_cache_at_idx on answer_cache (at desc);

-- Cached answers outlive the code that produced them, so the version that
-- wrote each row is recorded and forms part of the key.
alter table answer_cache add column if not exists version text;
