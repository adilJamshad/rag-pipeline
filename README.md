# rfc-rag

Answering "what is the current specification for X?" over IETF RFCs — correctly, including everything that changed it.

**Status: in progress.** Numbers below are measured on this machine; sections marked *planned* are not built yet.

## The problem

RFCs are never edited. When a specification changes, a new RFC is published that **obsoletes** or **updates** the old one. The old document stays online, unchanged, looking authoritative.

So three things go wrong when you search them:

1. **Dead specs look alive.** 1,384 of 9,854 RFCs (14%) have been replaced. RFC 2616 was obsoleted in 2014 and is still the top search result for HTTP.
2. **Live specs are silently incomplete.** RFC 1035 (DNS) has *never* been obsoleted, so it reads as current — but 29 later RFCs have modified it. Returning it alone is wrong by omission, which is the worst failure mode because it looks right.
3. **Errata are invisible.** 2,483 RFCs carry published corrections that are not in the document text.

## Approach

**The LLM never decides a fact.** Supersession is a SQL query over published metadata, so it cannot be hallucinated. The model only writes prose around facts the database already proved, and quotes specification text verbatim rather than paraphrasing it.

Three routes, chosen by rule, with the route logged per question:

| Route | Example | Engine |
|---|---|---|
| `facts` | "Is RFC 2065 obsolete?" · "What updated RFC 1035?" | SQL only |
| `passage` | "What is the maximum label length?" | Search, display verbatim |
| `synthesis` | "What is the current DNS spec?" | LLM over retrieved passages + SQL facts |
| refusal | "How do I configure BIND9?" | Below confidence threshold — say so |

## Why retrieval, not a long context window

The model here has a 128k context. The whole corpus does not fit, but a single RFC does — so this was worth measuring rather than assuming:

| Input | Time | Result |
|---|---|---|
| Whole of RFC 1035 (24,553 tokens) | **82.2s** | no answer — reasoning consumed the entire output budget |
| Retrieved section only (175 tokens) | **2.0s** | correct, with exact quotes |

41x faster, and the only one that answered. Retrieval here buys correctness, not just context-window relief.

## Scope

DNS family: RFC 1034 and 1035, everything that updates them, plus one hop. **70 RFCs, 1,207 pages, ~800k tokens.** 20 of those 70 are already obsolete and 31 carry errata, so all three failure modes are live inside the slice.

Deliberately excluded: auth, chat history, agents, fine-tuning, the other 9,784 RFCs.

## Stack

Everything runs locally.

- **Postgres 17 + pgvector 0.8.7** (port 5433) — facts, full-text search and vectors in one database, so retrieval can be filtered by supersession status in the same query
- **gpt-oss-20b** via oMLX — answer generation
- **bge-small-en-v1.5** (384 dims) — embeddings
- Python 3.12, `uv`

Swappable via one adapter: any OpenAI-compatible endpoint, including Apple Foundation Models and OpenAI itself.

## Evaluation *(planned)*

The supersession graph is published metadata, so gold labels for the `facts` route are generated, not hand-written. Baseline is Postgres full-text search alone; every addition must beat it on the eval set or be dropped.

Early signal on a 4-question probe: full-text search 1/4, embeddings 4/4 — full-text found nothing when the question shared no vocabulary with the text ("stop someone forging fake DNS answers" vs "origin authentication"). Four questions prove nothing; it is recorded here as the reason the eval set is being built before the retrieval work.

## Running it

    uv sync
    docker compose up -d
    uv run pytest
