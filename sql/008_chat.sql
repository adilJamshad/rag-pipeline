create extension if not exists pgcrypto;

create table if not exists chat (
    id            uuid primary key default gen_random_uuid(),
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    title         text,
    client        text,
    state         text not null default 'open'
                  check (state in ('open', 'readonly')),
    token_budget  int  not null default 30000,
    tokens_used   int  not null default 0,
    message_count int  not null default 0
);

create table if not exists message (
    id           bigserial primary key,
    chat_id      uuid not null references chat(id) on delete cascade,
    at           timestamptz not null default now(),
    position     int  not null,
    role         text not null check (role in ('user', 'assistant')),
    content      text not null,

    route        text,
    quote        text,
    verified     boolean,
    sources      jsonb,
    tokens_in    int,
    tokens_out   int,
    resolved_question text,

    unique (chat_id, position)
);

create index if not exists chat_client_idx on chat (client, updated_at desc);
create index if not exists message_chat_idx on message (chat_id, position);
