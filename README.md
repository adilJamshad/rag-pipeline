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

**417 RFCs, 9,572 sections, 3.6M tokens** — every DNS-related RFC, selected by working group, index keywords and title, then closed over the supersession graph.

An earlier version selected the corpus by following `updates`/`obsoletes` links out from RFC 1034 and 1035. That rule is wrong in a way worth recording: **new protocols do not update old ones, they reference them**, so it silently excluded DNS over HTTPS, DNS over TLS, DNS over QUIC, Multicast DNS, DNS-SD, DANE, NSEC3, Client Subnet, Extended DNS Errors and SVCB — twelve of fifteen major DNS RFCs, and most of what anyone asks about today.

It also corrupted the evaluation. The old identifier set asked about *NSEC3* and scored 1.00, while RFC 5155 — the document that defines NSEC3 — was not in the corpus at all. The gold pointed at two passing mentions elsewhere. The set could not detect the omission because it had been built by searching the corpus instead of from the domain.

Deliberately excluded: auth, chat history, agents, fine-tuning, the other ~9,500 non-DNS RFCs.

## Evaluation

Questions are written **before** looking at the corpus, and each names the RFC that should authoritatively answer it, from domain knowledge. Retrieval is therefore scored at document level against a gold document that search did not choose.

**30 answerable questions · 10 unanswerable · 2,085 generated fact questions.**

### Retrieval

| Method | doc@1 | doc@5 | doc@10 | MRR |
|---|---|---|---|---|
| Full-text (all terms) | 0.20 | 0.50 | 0.60 | 0.333 |
| **Semantic** | 0.27 | **0.73** | **0.83** | **0.441** |
| Hybrid (RRF) | **0.30** | 0.57 | 0.70 | 0.424 |

### Answers

| | |
|---|---|
| Answered | 29/30 |
| **Contained the expected fact** | **29/29** |
| Quote verified verbatim | 25/29 |
| Cited the authoritative RFC | 20/29 |
| False refusals | 1 |
| Unanswerable correctly refused | **7/10** |

### Three results that corrected earlier claims

**1. "Hybrid search is worse" was too strong.** On the old 76-document corpus hybrid lost on every metric. On 417 documents it has the **best doc@1 of the three** (0.30 vs semantic's 0.27), while still losing on MRR and doc@10. The honest statement is that full-text contributes little here and hurts deep ranking, not that fusion is wrong.

**2. A larger corpus made refusal harder, not easier.** Correct refusals fell from 9/10 to 7/10. *"How do I configure BIND9?"* is now answered, because RFC 2308 §9.2 is literally titled "BIND". More documents means more plausible-looking material for an unanswerable question to latch onto.

**3. Correctness is measured, and the measure is weak.** Each question carries a string its answer must contain — "63", "853", "512". That caught zero errors, but several checks are lenient: *"What is an SVCB record?"* passes on the substring "service". It establishes that answers are not wildly wrong. It does not establish that they are right.

### What this evaluation still cannot tell you

- **Section-level precision.** Gold sections are chosen by embedding similarity within the correct document, which is circular. Only the document-level number is independent.
- **Whether the quote supports the answer.** Grounding proves the quote exists in a cited section, nothing more.
- 30 questions is a small sample and I wrote all of them.

## What I expected vs what I measured

Every row here was a belief I held before building, overturned by a measurement. The reasons matter more than the scores.

| # | What I expected | What I measured | Why |
|---|---|---|---|
| 1 | A 128k context window makes retrieval unnecessary for one document | Whole RFC 1035: **82s, no answer**. Retrieved section: **2.0s, correct with quotes** | Prefill dominates (57s for 24.5k tokens) and reasoning tokens consumed the entire output budget before any answer was produced |
| 2 | Hybrid search (keyword + semantic) beats either alone — standard practice | Hybrid **MRR 0.317** vs semantic **0.483**; worse at every weight tested | Reciprocal rank fusion scores `weight/(60+rank)` with no term for ranker quality, so both get an equal vote. Keyword is right at rank 1 only 10% of the time, so ~90% of its votes push correct results down |
| 3 | Keyword search wins on exact identifiers like NSEC3 and QDCOUNT | Both reach R@5 1.00; semantic still ranks better (**0.704** vs 0.674) | Sections are embedded as *title + body*, and RFC titles **are** the identifiers. Removing titles halved identifier MRR to 0.353, confirming the embedding already carried the lexical capability |
| 4 | Postgres full-text search is roughly BM25 | Matching *any* term (0.15) scored **worse** than requiring *all* terms (0.30) | `ts_rank` uses only within-document frequency and position. It has no corpus statistics, so no rarity weighting — matching "DNS" counts as much as matching "QDCOUNT" |
| 5 | The small local model hit its context limit around 6,000 words | It was a **safety guardrail** firing on repeated filler, not a size limit | Real prose established the actual ceiling at ~4k tokens. Synthetic test data produced a misleading failure mode |
| 6 | Parse the canonical `.txt` RFCs | Parsed the HTML instead | The text files are paginated with form feeds that cut sentences mid-word — RFC 1035 contains 55 of them. The HTML carries `id="section-N.N"` anchors in every era, including 1981 |
| 7 | One parser handles the corpus | **Three** document shapes | Modern RFCs nest `<section>` elements; legacy ones are flat `<pre>` with heading spans; five pre-2002 documents have no anchors at all and need paragraph chunking |
| 8 | Excluding nested sections by tag check would prevent duplication | RFC 9110 parsed to **285k tokens** against a real size of ~110k | Nested sections are wrapped in `<div>`, so a parent's direct children are divs, not sections, and the check never fired. Nothing errored — the only signal was an implausible token count |
| 9 | Gold labels could be derived automatically by substring match | 21 of 25 seeds hit the candidate ceiling; hand-labelling was unavoidable | Terms like "root", "compression" and "authoritative" appear across dozens of sections. Only the *supersession* labels could be generated, because those are published metadata |
| 10 | The LLM answers the questions | Most questions need **no LLM at all** | "Is RFC 2065 current?" is a SQL lookup over published metadata. Routing it to a model adds latency and introduces the one failure mode the project exists to prevent |
| 11 | A vector database would be needed | Postgres alone does facts, full-text and vectors | At 1,705 sections a separate vector store adds a join-by-hand problem and buys nothing. pgvector keeps supersession filtering in the same query |
| 12 | A similarity threshold separates answerable from unanswerable questions | Distributions overlap: worst answerable **0.687**, best unanswerable **0.688** | Cosine similarity measures topical closeness, not whether a passage answers a question. "Write me a Python script to query DNS" is about DNS and retrieves DNS text; the specs simply do not answer it |
| 13 | Demoting obsolete RFCs would improve the scores | MRR moved 0.483 → 0.488, but the top-5 for "SOA record fields" lost both dead 1983 documents | The eval set measures whether gold was found, not whether junk was avoided. A metric can miss a real user-facing improvement |

## Running it

    uv sync
    docker compose up -d
    uv run pytest
