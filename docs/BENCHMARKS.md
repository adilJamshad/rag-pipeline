# Performance

Quality is measured by the evaluation harness. This is the other half: where a
request's time goes, how much load the system takes, and what gives out first.

Run with `uv run python bench/components.py` and `uv run python bench/load.py`.

## Where a request's time goes

| Stage | median | worst |
|---|---|---|
| analyse + plan (pure) | **0.0 ms** | 0.0 ms |
| embed the question (in-process) | 2.2 ms | 406 ms (first call, model load) |
| corpus stamp check, warm | **0.0 ms** | 0.0 ms |
| corpus stamp check, cold | 10.0 ms | 22.7 ms |
| supersession lookup | 6.9 ms | 7.0 ms |
| `current_for` chain | 6.2 ms | 6.8 ms |
| keyword search, k=6 | 6.1 ms | 9.1 ms |
| vector search, k=6 | 29.9 ms | 53.6 ms |

A full synthesis request, broken down by the trace:

```
total 1000 ms
  analyse      0 ms
  gather      24 ms
  generate   904 ms     <- 90% of the request
  verify      50 ms
```

**Retrieval is 2.4% of a request.** Optimising it would be measuring the wrong
thing; the model call is everything.

## Throughput

| Path | c=1 | c=4 | c=8 | c=16 |
|---|---|---|---|---|
| Vector search | 34 req/s | 118 | **166** | 168 |
| Supersession lookup (SQL) | 156 req/s | — | **432** | 350 |
| Embedding (in-process CPU) | 481 req/s | 868 | **1015** | — |

No errors at any concurrency. Facts-route throughput peaks at 8 and falls at
16, which is connection contention, not CPU.

## The provider is the ceiling, by a factor of 300

| | throughput |
|---|---|
| Our retrieval | 168 req/s |
| Our facts route | 432 req/s |
| **Groq free tier** | **30 requests/minute = 0.5 req/s** |

Measured, not quoted — the error says so:

```
Rate limit reached for model `openai/gpt-oss-20b` ...
on requests per minute (RPM): Limit 30, Used 30, Requested 1
```

### Two things this corrected

**The eval's latency columns were measuring our own retry backoff.** Run 1
recorded p50 7.7 s against a local model; run 2 recorded 14.0 s against Groq,
which is *faster* per call. The difference is four 2-second waits while
backing off a 429. `p50_ms` and `p95_ms` in `eval_run` therefore describe the
provider's free tier, not the system, whenever the eval outruns 30 RPM.

**The rate limits did not match the provider's.** Six clients at
`RATE_PER_MINUTE=6` is 36 requests a minute against a ceiling of 30, and
nothing counted requests across clients — `GLOBAL_PER_DAY=800` is far below
what 30/minute permits, so the daily cap never binds first. Six concurrent
users would have pushed the service into provider 429s, which the API turns
into 503s for everyone.

`GLOBAL_PER_MINUTE` (default 25) now caps the whole service below the
provider's ceiling. **Set it below whatever your provider allows.**

## What this means for deployment

Nothing in this system needs scaling. One process serves hundreds of requests
per second and the provider allows 0.5. The capacity question is entirely
"which model tier", and the engineering question is how much traffic can be
answered **without** the model — which is why the facts and passage routes
exist, and why they are 432 req/s rather than 0.5.
