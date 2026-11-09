# LLM backend adapters

Three implementations of the same contract (`clients/base.py`), selected by
`LLM_BACKEND` and chained by `LLM_FALLBACKS`. All three were run against the
same local server on the same question; every number below is measured, not
quoted from documentation.

## Measured

| | direct | langchain | llamaindex |
|---|---|---|---|
| Lines of adapter code | 78 | **46** | **41** |
| Extra packages | **0** | +7 | +12 |
| Cold import | **0.86 s** | 4.40 s | 8.43 s |
| `complete()` warm, mean of 3 | 1.40 s | **1.33 s** | 1.34 s |
| `embed()` 3 strings | 0.05 s | 0.10 s | **0.03 s** |
| Provider-specific params | native | `extra_body=` | `additional_kwargs=` |
| Handles oMLX's forced SSE | **yes** | n/a (its own client) | n/a |

Core project alone is 22 packages and a 39 MB virtualenv. With both frameworks
installed it is 93 packages and **181 MB** — a 4.6x increase for code paths
that produce byte-identical answers.

**Latency is indistinguishable.** All three sit at ~1.33 s because the local
model dominates; the client library contributes noise. Any benchmark claiming
one framework is "faster" at this is measuring warm-up.

---

## `direct` — httpx against the OpenAI-compatible endpoint

**Pros**
- No dependency beyond `httpx`, which the project already needs.
- Fastest import by 5x, which matters for a CLI invoked per question.
- Provider-specific parameters are just JSON keys. `reasoning_effort: "low"`
  is passed natively — on gpt-oss that is the difference between 8.8 s and
  2.0 s, so it is not optional here.
- Handles the quirks we actually hit: oMLX streams even when `stream` is not
  requested, and gpt-oss returns empty `content` when reasoning ate the token
  budget. Both are explicit in 78 readable lines.
- Errors are ours, so stack traces point at our code.

**Cons**
- Retries, backoff, token counting and streaming are ours to write.
- No ecosystem: no ready-made caching, callbacks or tracing integrations.
- A provider with a genuinely different API shape means new code.

## `langchain` — `ChatOpenAI` + `OpenAIEmbeddings`

**Pros**
- Smallest adapter at 46 lines.
- The ecosystem is the real argument: LangSmith tracing, caching, callbacks
  and retrievers are one import away. This project persists no traces yet,
  which is exactly the gap LangSmith fills.
- Swapping to Anthropic, Bedrock or Vertex is a class change, not a rewrite.

**Cons**
- +7 packages and +4.4 s of import time for a CLI.
- Provider-specific parameters are second-class: `reasoning_effort` only
  reaches the server through the `extra_body` escape hatch. Miss that and
  gpt-oss silently returns empty content.
- The HTTP call is three layers down, so debugging a malformed request means
  reading framework source.
- Historically frequent breaking changes across minor versions.

## `llamaindex` — `OpenAILike` + `OpenAIEmbedding`

**Pros**
- Smallest adapter at 41 lines, fastest batch embedding.
- `OpenAILike` is built for exactly this case: a server that speaks the OpenAI
  API but is not OpenAI.
- Strongest RAG-specific tooling if you want it — node parsers, index
  abstractions, query engines.

**Cons**
- Slowest import at 8.4 s, and +12 packages including `nltk` and three
  `griffe` packages this project will never use.
- Its document/node model duplicates our `section` table and `models.Section`.
  Adopting it would mean two representations of the same data.
- Provider parameters go through `additional_kwargs`, same escape-hatch
  problem as LangChain.

## Hosted API (OpenAI, Groq, Together, …)

Not a fourth backend — it is `direct` with a different URL:

    LLM_BASE_URL=https://api.openai.com/v1
    LLM_MODEL=gpt-4o-mini
    LLM_API_KEY=sk-...

All three backends work this way, since all three target the OpenAI wire
format. Worth stating plainly: **the adapter buys provider portability, and
the frameworks do not add any portability the direct client lacks** for
OpenAI-compatible servers.

---

## Redundancy: what the fallback chain actually protects against

    LLM_BACKEND=direct
    LLM_FALLBACKS=langchain,llamaindex

On failure, `clients/llm.py` tries each in order and records which answered in
`llm.last_used`. Verified by breaking `direct` at runtime: the call was served
by `langchain` and returned the right answer.

**But be honest about the threat model.** All three talk to the same endpoint,
so a fallback helps only when the failure is *in the client library* — a
serialisation bug, a dependency conflict, a breaking framework release. It
does **not** help when the server is down, the model is unloaded, the context
is exceeded or a rate limit is hit, which are the failures that actually
happen. Those need a different *endpoint*, not a different *client*.

Real redundancy is therefore `LLM_BASE_URL` pointing somewhere else, not
`LLM_FALLBACKS`. The chain is kept because it is nearly free, it makes the
comparison runnable, and it costs 58 lines.

## What is actually shipped

`LLM_BACKEND=direct`, no fallbacks, and the frameworks in an optional
dependency group (`uv sync --group frameworks`) so the default install stays
at 22 packages.

The frameworks are not used because this project uses none of what they are
for. There are no chains, no agents, no node parsing — retrieval is SQL and
the pipeline is seven functions. They earn their place the moment we want
LangSmith tracing, or a provider that does not speak the OpenAI format.
