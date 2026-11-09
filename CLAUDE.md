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

## Commands

    uv sync                                      install
    docker compose up -d                         start postgres
    uv run python -m rfc_rag.ingest.run          build the corpus
    uv run python -m rfc_rag.ingest.embeddings   fill vectors
    uv run python -m rfc_rag.evaluation.run      score it
    uv run rfc "<question>"                      ask
    uv run pytest                                tests

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
