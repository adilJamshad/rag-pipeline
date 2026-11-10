create table if not exists corpus_meta (
    id          int primary key default 1,
    embed_model text not null,
    embed_dim   int  not null,
    embed_base  text,
    embedded_at timestamptz not null default now(),
    constraint corpus_meta_single_row check (id = 1)
);
