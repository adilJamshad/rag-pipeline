create table if not exists eval_run (
    id          bigserial primary key,
    at          timestamptz not null default now(),
    git_sha     text,
    dirty       boolean,
    label       text,

    retrieval   text,
    llm_model   text,
    embed_model text,
    backend     text,
    corpus_docs int,
    corpus_sections int,

    n_questions int,
    doc_r1      numeric(4,3),
    doc_r5      numeric(4,3),
    doc_r10     numeric(4,3),
    mrr         numeric(4,3),

    answer_rate numeric(4,3),
    correct     numeric(4,3),
    grounded    numeric(4,3),
    cited_right numeric(4,3),
    false_refusal_rate numeric(4,3),
    refusal_accuracy   numeric(4,3),

    p50_ms      int,
    p95_ms      int,
    tokens_in   int,
    tokens_out  int,
    llm_calls   int,

    extra       jsonb
);

create table if not exists eval_result (
    run_id      bigint not null references eval_run(id) on delete cascade,
    question_id text   not null,
    question    text,
    kind        text,
    gold_rank   int,
    route       text,
    correct     boolean,
    grounded    boolean,
    cited_right boolean,
    total_ms    int,
    primary key (run_id, question_id)
);

create index if not exists eval_run_at_idx on eval_run (at desc);
