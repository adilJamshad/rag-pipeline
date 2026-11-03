# rfc-rag

Question answering over IETF RFCs, scoped to the DNS family. Portfolio project; learning the domain is an explicit goal, so explain protocol concepts rather than assuming them.

Machine-specific setup (model endpoints, credentials, ports) lives in `CLAUDE.local.md`, which is not committed.

## The one rule

**The LLM never decides a fact.** Whether an RFC is current, what replaced it, what updated it — those come from SQL only. The LLM receives facts the database already proved and writes sentences around them. A model answer that contradicts the database is a bug in routing, not a prompting problem.

Corollary: quote RFC text verbatim. Never paraphrase a specification.

## Scope

DNS slice only: RFC 1034 and 1035 plus everything that updates them, plus one hop. 70 RFCs, ~1,200 pages. Do not ingest all 9,854 RFCs without a decision to widen.

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

## Commands

    uv sync                       install
    docker compose up -d          start postgres
    uv run pytest                 tests
    psql $DATABASE_URL            open the db

## Conventions

- No explanatory comments in code. Only a one-line `shortcut: <limit>, <when to upgrade>` where a deliberate corner was cut.
- Every new non-trivial branch, parser or scoring function gets a small test.
- Measure before optimising. Full-text search is the baseline and may win; report it honestly either way.
