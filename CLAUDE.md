# rfc-rag

Question answering over IETF RFCs, scoped to the DNS family. Portfolio project; learning the domain is an explicit goal, so explain protocol concepts rather than assuming them.

Machine-specific setup (model endpoints, credentials, ports) lives in `CLAUDE.local.md`, which is not committed.

## The one rule

**The LLM never decides a fact.** Whether an RFC is current, what replaced it, what updated it — those come from SQL only. The LLM receives facts the database already proved and writes sentences around them. A model answer that contradicts the database is a bug in routing, not a prompting problem.

Corollary: quote RFC text verbatim. Never paraphrase a specification.

## Scope

Every DNS-related RFC, selected by working group, index keywords and title (`index.is_dns`), then closed over the supersession graph. 417 documents, 9,572 sections, 3.6M tokens.

**Do not revert to graph-based selection.** Choosing the corpus by following updates/obsoletes out from RFC 1034/1035 excluded DoH, DoT, DoQ, mDNS, DNS-SD, DANE, NSEC3, Client Subnet, Extended DNS Errors and SVCB — new protocols reference the base specs, they do not update them. `test_topic_corpus_includes_modern_dns_rfcs` guards this.

Not in scope: auth, chat history, agents, fine-tuning, multimodal.

## Three answer paths

Route by rule, not by model. Log which path each question took.

- `facts` — is it current, what replaced it, what updated it, when published. SQL only, no LLM.
- `passage` — find text inside documents. Search, then display verbatim. No LLM.
- `synthesis` — needs several documents combined, or a yes/no extracted from dense prose. LLM, given only retrieved passages and SQL facts.
- Nothing above the confidence threshold: say so, show the near misses and their scores.

## Stack

- Python 3.12 via `uv`
- Postgres 17 + pgvector on port 5433, via `docker compose up -d`
- Retrieval: Postgres full-text search and pgvector, compared against each other
- LLM and embeddings: any OpenAI-compatible endpoint, through `src/rfc_rag/llm.py`

## Corpus gotchas

- Parse the **HTML**, not the `.txt`. The text files are paginated with form feeds that cut sentences in half (RFC 1035 has 55 of them).
- Every RFC's HTML has `id="section-N.N"` anchors, including 1980s ones. That is the chunk boundary.
- Modern RFCs have paragraph-level anchors too; old ones only section-level. Normalise to section.
- `<pre>` blocks hold ASCII diagrams and ABNF grammar, 50-160 per RFC. They embed badly. Keep them verbatim and index a description alongside.
- The index at `https://www.rfc-editor.org/rfc-index.xml` uses namespace `https://www.rfc-editor.org/rfc-index` (https, not http). `/in-notes/rfc-index.xml` is a dead path.
- Supersession fans out and chains: RFC 2616 is obsoleted by six RFCs at once; some chains run 33 deep. The deepest ones are the old periodically-republished "Internet Official Protocol Standards" meta-RFCs — exclude them from graph statistics deliberately.
- 9,854 RFCs total; 1,384 obsoleted, 1,242 updated, 2,483 carry errata.

## Layout

- `models.py` holds **every** dataclass. Do not define a dataclass anywhere else.
- `services/stages.py` is **pure** — no db, no network, no model. `services/answering.py` holds everything with side effects. Keep that line; it is why the suite runs without a model server.
- `clients/` holds three interchangeable LLM backends behind `base.LLMBackend`. `_direct` is the default and the only one installed by default; `_langchain` and `_llamaindex` need `uv sync --group frameworks`. See `docs/ADAPTERS.md` for the measured comparison — do not switch the default without numbers.
- Both frameworks need an escape hatch to pass `reasoning_effort` (`extra_body` for LangChain, `additional_kwargs` for LlamaIndex). Omit it and gpt-oss returns empty content.
- `LLM_FALLBACKS` only protects against client-library failures, not server outages: every backend hits the same endpoint. Real redundancy is a second `LLM_BASE_URL`.
- `clients/` wraps anything outside the process, `ingest/` builds the corpus, `services/` answers questions, `interfaces/` exposes it, `evaluation/` measures it.

## HTTP API

`interfaces/api.py` plus `interfaces/guards.py`. Rules:

- Never let an upstream exception reach a caller. Backends raise `LLMError`; the API turns a 429 into 503 + Retry-After and everything else into a generic 502/500. Tests assert no URL, key or connection string appears in an error body.
- `check_burst` is in-process and must stay database-free; `check_quota` is database-backed and is the one that survives restarts and multiple instances. On serverless, only `check_quota` is meaningful.
- `GLOBAL_PER_DAY` is the cap protecting the model quota. Do not raise it without a reason.
- `/ask` responses must keep naming every RFC researched, with status — that is the product, not a debugging aid.
- The answer cache key includes `CACHE_VERSION`. **Bump it when routing, prompts or answer shape change**, or a question answered wrongly keeps serving that answer for the whole TTL, outliving the fix.
- Model output is validated by `stages.clean_response` before anything indexes or `.strip()`s it. A wrong type is a refusal, never a 500.

## Concurrency

FastAPI runs sync endpoints in a **threadpool**, so anything at module level is shared between in-flight requests. Three bugs came from ignoring that, all now covered by `tests/test_concurrency.py`:

- Per-request state (`last_used`, `last_usage`) must be `threading.local()`. As module globals, 3 of 4 threads read another request's token counts.
- Read-then-write against a row needs `select ... for update`. `chat.send` read `message_count` outside the transaction, so concurrent sends picked the same position and the unique constraint returned a 500 to the user.
- Never identify a row with `max(id)`. `_tag` did, and wrote one request's client onto another's log row. Pass the id instead — `observability.record` sets `trace.log_id`.

Also: `guards._minute` is swept, because one never-expiring entry per client IP retained ~39 MB at 50,000 callers.

## MCP

`interfaces/mcp_server.py`, mounted at `/mcp` in the same process as the API so both share the in-process limiters and the provider budget.

- **Do not add a synthesis tool.** The client has its own model; ours summarising so theirs can paraphrase loses information twice and spends the quota. Return sections, not answers.
- Keep the tool count low. Definitions are re-sent on every turn — three tools is ~400 tokens of someone else's context budget, forever.
- The docstring **is** the description the model reads when choosing the tool, and the type hints generate the schema. Write them as prompts, and say *when* to use the tool, not only what it returns.
- SDK is mcp 2.x: `MCPServer`, not `FastMCP`; `input_schema`, not `inputSchema`. Most examples online are v1. Pinned `mcp>=2.3,<3`.
- FastAPI does not run a mounted sub-app's lifespan. The MCP app is built first and its `lifespan_context` passed to `FastAPI(...)`, or every call fails with "Task group is not initialized".
- v2 runs sync tools on worker threads, so MCP tools are concurrent by default. See the Concurrency section.

## Observability

Every question is recorded to `query_log` from inside `ask()`. Recording is wrapped so it can never break answering — failures are logged, never raised. `QUERY_LOG=0` disables it; `rfc --stats` reports.

Retention: `uv run python -m rfc_rag.observability [days]` prunes `query_log`, `chat` (messages cascade) and `answer_cache` past `RETENTION_DAYS`, default 90. `eval_run` is kept deliberately — it is the regression history.

Real token counts come from `llm.last_usage`, which only the `direct` backend populates — the framework backends do not surface usage, so those rows have null token columns.

## CI and schema

- **Every schema change goes in a file under `sql/`.** `chat.max_messages` was once typed into psql directly and CI caught the drift weeks later. Migrations must be safe to re-run: `create table if not exists`, `add column if not exists`.
- `tests/conftest.py` applies all migrations and seeds a fixture corpus, so the suite must pass against an **empty** Postgres, not just a loaded machine.
- No test may leave `corpus_meta` changed; an autouse fixture restores it.
- `eval/baseline.json` is the quality gate. Do not edit it to make a build pass — `--save-baseline` rewrites it, and a drop should be justified in the diff.
- `false_refusal_rate` is watched inverted. Refusing more makes every other metric look better, so it is the metric that keeps the others honest.

## Commands

    uv sync                                      install
    docker compose up -d                         start postgres
    uv run python -m rfc_rag.ingest.run          build the corpus
    uv run python -m rfc_rag.ingest.embeddings   fill vectors
    uv run python -m rfc_rag.evaluation.run      score it
    uv run rfc "<question>"                      ask
    uv run rfc --stats                           usage, latency, failures
    uv run pytest                                tests
    uv run python -m rfc_rag.evaluation.gate     eval against the committed baseline

## Conventions

- No explanatory comments in code. Only a one-line `shortcut: <limit>, <when to upgrade>` where a deliberate corner was cut.
- Every new non-trivial branch, parser or scoring function gets a small test.
- Measure before optimising. Full-text search is the baseline and may win; report it honestly either way.

## Measured results

Semantic is the default. 30 answerable questions, gold document named from the domain before searching:

| | doc@1 | doc@5 | doc@10 | MRR |
|---|---|---|---|---|
| full-text (all terms) | 0.20 | 0.50 | 0.60 | 0.333 |
| semantic | 0.27 | **0.73** | **0.83** | **0.441** |
| hybrid RRF | **0.30** | 0.57 | 0.70 | 0.424 |

Answers: 29/30 answered, 29/29 contained the expected fact, 25/29 quotes verified verbatim, 20/29 cited the authoritative RFC, 7/10 unanswerable correctly refused.

Notes for anyone changing retrieval:

- Hybrid has the best doc@1 but loses on MRR and doc@10. On the earlier 76-document corpus it lost on everything, so that claim was corpus-specific and has been softened in the README.
- Refusal got **worse** as the corpus grew (9/10 to 7/10). "How do I configure BIND9?" is now answered because RFC 2308 §9.2 is titled "BIND".
- The correctness check is a substring match (`expect` in eval/questions.py). It is lenient; treat 29/29 as "not wildly wrong", not as accuracy.
- Gold sections within the correct RFC are chosen by embedding similarity, so only document-level retrieval numbers are independent.
