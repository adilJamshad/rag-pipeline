FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HUB_DISABLE_TELEMETRY=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY sql ./sql
COPY eval ./eval
COPY data/corpus.sql.gz ./data/corpus.sql.gz
COPY scripts/start.sh ./scripts/start.sh
RUN uv sync --frozen --no-dev && chmod +x scripts/start.sh

# Bake the embedding weights in. Downloading them on first request would make
# the first caller wait ~20s, and a container without network egress to the
# model hub would never start serving at all.
RUN uv run python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

CMD ["./scripts/start.sh"]
