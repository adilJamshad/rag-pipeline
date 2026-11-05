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

## Evaluation

Three sets. **380 fact questions** are generated from the supersession graph, so their gold answers are published metadata rather than opinion. **20 passage questions** and **12 identifier questions** are hand-written, with every gold section verified to exist in the corpus before the set is accepted.

Retrieval, measured end to end:

| Method | passages R@1 | R@5 | R@10 | MRR | identifiers R@5 | MRR |
|---|---|---|---|---|---|---|
| Full-text, all terms | 0.10 | 0.25 | 0.30 | 0.148 | 1.00 | 0.674 |
| Full-text, any term | 0.05 | 0.10 | 0.15 | 0.067 | 0.33 | 0.158 |
| **Semantic (bge-small)** | **0.35** | **0.65** | **0.80** | **0.483** | **1.00** | **0.704** |
| Hybrid (RRF) | 0.20 | 0.40 | 0.70 | 0.317 | 0.83 | 0.604 |

### Three findings worth stating

**1. Semantic search beats full-text by 2.7x on natural-language questions** — 0.30 to 0.80 at R@10.

**2. Hybrid search makes things worse, at every weighting.** Sweeping the keyword weight into reciprocal rank fusion gives a monotonic decline:

| keyword weight | 0.0 | 0.1 | 0.25 | 0.5 | 1.0 | 2.0 |
|---|---|---|---|---|---|---|
| passages MRR | **0.483** | 0.404 | 0.338 | 0.322 | 0.317 | 0.192 |

The optimum is zero keyword. RRF assumes the rankers it merges are comparably good; here full-text is weak enough that mixing it in only adds noise. Hybrid retrieval is standard advice, and on this corpus it is wrong.

**3. Full-text does not win even on exact identifiers.** The identifier set ("NSEC3", "QDCOUNT", "SOA RDATA format") was built specifically to be full-text's best case. Both methods reach R@5 1.00 and semantic still ranks better (MRR 0.704 vs 0.674).

So the shipped default is semantic alone. Full-text and hybrid stay in the codebase because the measurement is part of the result.

### Honest limits

32 hand-labelled questions is a small sample and the confidence intervals are wide. Several "misses" are arguably correct — asked "what is a stub resolver?", retrieval returns RFC 4033 §7 *Stub Resolver Considerations* while the gold is RFC 1034 §5.3.1, so true quality is likely higher than 0.80. The fact set is large (380) but easy; it tests the SQL route, which cannot hallucinate by construction.

## Running it

    uv sync
    docker compose up -d
    uv run pytest
