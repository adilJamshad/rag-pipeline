create table if not exists query_log (
    id              bigserial primary key,
    at              timestamptz not null default now(),
    question        text        not null,
    route           text,
    answered        boolean     not null,
    grounded        boolean,
    backend         text,
    llm_calls       int         not null default 0,
    total_ms        int,
    timings         jsonb,
    context_tokens  int,
    prompt_tokens   int,
    completion_tokens int,
    retrieved       text[],
    cited           int[],
    topic_rfc       int,
    answer          text,
    quote           text,
    error           text
);

create index if not exists query_log_at_idx on query_log (at desc);
create index if not exists query_log_route_idx on query_log (route, at desc);
