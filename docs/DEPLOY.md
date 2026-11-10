# Deploying for free

Three pieces, each with a genuine free tier.

| Piece | Service | Free allowance | Why it fits |
|---|---|---|---|
| Database | **Neon** | 0.5 GB | pgvector is supported; this corpus is **99 MB** |
| API | **Hugging Face Spaces** (Docker) | always free | public demos are the intended use; sleeps after long idle, wakes on request |
| Model | **Gemini** free tier | rate limited | `gemini-3.1-flash-lite` for chat, `gemini-embedding-001` for vectors |

Total: **$0**, with rate limits as the only real constraint — which is exactly what `interfaces/guards.py` exists to manage.

## Why these

**Neon over Supabase** — both free and both ship pgvector; Neon's branching makes it easy to keep a throwaway copy for eval runs. Either works.

**Hugging Face Spaces over Render or Fly** — Render's free web services spin down after 15 minutes idle and cold-start in ~50 seconds, which is a poor first impression for a portfolio link. Fly's free allowance is now usage-credit based rather than a standing free tier. Spaces stays genuinely free for a public demo.

**Not serverless** (Vercel, Lambda). Each invocation would pay a cold start, and the per-process rate limiter in `check_burst` only works within one process. On serverless, delete it and rely on `check_quota`, which is database-backed and therefore shared.

## Steps

**1. Database**

Create a Neon project, then from your machine:

    psql "$NEON_URL" -f sql/001_schema.sql
    psql "$NEON_URL" -f sql/002_chain.sql   # and 003..007
    pg_dump -d "$LOCAL_URL" --data-only -t rfc -t rfc_relation -t section -t corpus_meta \
      | psql "$NEON_URL"

Copying the data beats re-running ingestion: the corpus is ~10,000 embedding
calls, and the free model quota makes that take hours.

**2. Secrets** — set in the host's secret manager, never in the image:

    DATABASE_URL        the Neon connection string
    LLM_API_KEY         Gemini key
    LLM_BASE_URL        https://generativelanguage.googleapis.com/v1beta/openai
    LLM_MODEL           gemini-3.1-flash-lite
    EMBED_MODEL         gemini-embedding-001
    EMBED_DIM           384
    EMBED_DIMENSIONS    384
    METRICS_TOKEN       anything — /metrics is public without it

**3. Tune the limits** for a public demo. Defaults in `guards.py`:

    RATE_PER_MINUTE=6       per caller
    RATE_PER_DAY=60         per caller
    GLOBAL_PER_DAY=800      everyone, protects the model quota
    CACHE_TTL_HOURS=168     repeated questions never reach the model

`GLOBAL_PER_DAY` is the one that matters. It is a cap on *your* bill and *your*
quota, and it is deliberately below what the free tier allows.

**4. Deploy** — the `Dockerfile` builds and runs the API on port 8000.
`/healthz` returns 503 until every section is embedded, so it doubles as a
readiness probe.

## What a public deployment still needs

- **A cost ceiling you trust.** `GLOBAL_PER_DAY` is enforced in application
  code. If something bypasses it, Gemini's own quota is the backstop — verify
  the key is on the free tier with no billing account attached.
- **Nothing sensitive in the corpus.** RFCs are public domain, so there is no
  data-exposure surface here. That is a property of this project, not a
  general safety argument.
- **An abuse story for the model.** The prompt only ever contains retrieved RFC
  text plus the question, the question is capped at 500 characters, and every
  claim must carry a quote that is verified against the source. A prompt
  injection can make the model refuse or ramble; it cannot make it fabricate a
  citation that passes `stages.verify`.
