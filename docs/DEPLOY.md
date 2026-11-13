# Deploying to Railway

Two services in one project: the app, and Postgres with pgvector. Verified by
building the image and booting it against an empty database before any of this
touched Railway.

## 1. The database

**Do not use Railway's standard Postgres** — it has no pgvector. Add a service
from the public image instead:

> New → Docker Image → `pgvector/pgvector:pg17`

Set its variables:

    POSTGRES_USER=rfc
    POSTGRES_PASSWORD=<something long>
    POSTGRES_DB=rfc

Railway exposes `DATABASE_URL` on that service; reference it from the app as
`${{Postgres.DATABASE_URL}}`.

## 2. The app

> New → GitHub Repo → this repository

Railway finds the `Dockerfile` and builds it. The image carries the corpus
(`data/corpus.sql.gz`, 24 MB) and the embedding weights, so a fresh container
serves correct answers on its first request. `scripts/start.sh` applies the
migrations, restores the corpus if the database is empty, then starts uvicorn
on `$PORT`.

Variables:

    DATABASE_URL=${{Postgres.DATABASE_URL}}
    GROQ_API_KEY=<your key>
    LLM_BASE_URL=https://api.groq.com/openai/v1
    LLM_MODEL=openai/gpt-oss-20b
    LLM_BACKEND=direct
    EMBED_BACKEND=local
    EMBED_MODEL=bge-small-en-v1.5
    EMBED_DIM=384
    METRICS_TOKEN=<something long>
    GLOBAL_PER_MINUTE=25
    MCP_PER_MINUTE=120

Then **Settings → Networking → Generate Domain**.

## 3. Check it

    curl https://<your-domain>/healthz

`status: ok` with `embedded: 9572/9572` means the corpus restored. It returns
`503` until then, which also makes it a correct readiness probe.

| | |
|---|---|
| Chat UI | `https://<domain>/` |
| Metrics | `https://<domain>/dashboard` |
| API docs | `https://<domain>/docs` |
| MCP | `https://<domain>/mcp/` |

Connect an MCP client:

```json
{"mcpServers": {"rfc-rag": {"url": "https://<your-domain>/mcp/"}}}
```

## What this actually costs

Railway's free plan is **$1 of credit a month**, and it bills for resources
rather than granting a free instance. An always-on container of roughly 1 GB
runs at about $10 a month, so **$1 does not buy a month of always-on**.

Two honest options:

- **Sleep enabled** (optional on the free plan). An occasionally-used demo
  stays inside $1. The cost is a cold start on the first request after idle,
  which an MCP client may experience as a timeout — Railway wakes faster than
  Render's ~50s, but it is not instant.
- **About $5 a month** for always-on. For a link on a CV that someone clicks
  once, a service that is actually up is worth more than the five dollars.

Either way the provider is the ceiling: Groq allows **30 requests a minute**,
so no amount of hosting makes this faster.

## Why the corpus ships in the image

The alternative is running ingestion on boot: downloading 417 documents from
rfc-editor.org (about six minutes, throttled) and embedding 9,572 sections.
Baking a 24 MB dump makes a cold container correct immediately, and makes the
build reproducible rather than dependent on a third-party site being up.

## Keeping it alive

`observability.prune` drops `query_log`, `chat` and `answer_cache` past
`RETENTION_DAYS` (90). Run it from Railway's cron, or on a schedule of your
choosing — nothing else removes those rows, and they grow with traffic.
