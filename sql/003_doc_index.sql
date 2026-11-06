alter table rfc add column if not exists abstract text;
alter table rfc add column if not exists embedding vector(384);

create index if not exists rfc_embedding_idx on rfc using hnsw (embedding vector_cosine_ops);
