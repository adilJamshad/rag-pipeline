create extension if not exists vector;

create table rfc (
    number      int primary key,
    title       text not null,
    year        int,
    status      text,
    stream      text,
    pages       int,
    errata_url  text
);

create table rfc_relation (
    src  int  not null references rfc(number),
    dst  int  not null references rfc(number),
    kind text not null check (kind in ('obsoletes', 'updates')),
    primary key (src, dst, kind)
);

create index on rfc_relation (dst, kind);

create table section (
    id      bigserial primary key,
    rfc     int  not null references rfc(number),
    anchor  text not null,
    number  text,
    title   text,
    body    text not null,
    tokens  int,
    has_pre boolean not null default false,
    embedding vector(384),
    fts tsvector generated always as (
        to_tsvector('english', coalesce(title, '') || ' ' || body)
    ) stored,
    unique (rfc, anchor)
);

create index on section using gin (fts);
create index on section using hnsw (embedding vector_cosine_ops);

create view rfc_status as
select
    r.*,
    exists (select 1 from rfc_relation x where x.dst = r.number and x.kind = 'obsoletes') as is_obsolete,
    (select array_agg(x.src order by x.src) from rfc_relation x where x.dst = r.number and x.kind = 'obsoletes') as obsoleted_by,
    (select count(*)      from rfc_relation x where x.dst = r.number and x.kind = 'updates') as update_count,
    (select array_agg(x.src order by x.src) from rfc_relation x where x.dst = r.number and x.kind = 'updates') as updated_by
from rfc r;
