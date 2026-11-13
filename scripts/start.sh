#!/usr/bin/env bash
# Restore the corpus once, then serve. Railway gives us $PORT and a managed
# database; the corpus ships in the image because rebuilding it means ~10,000
# embedding calls and a six-minute download from rfc-editor.org.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
PORT="${PORT:-8000}"

echo "applying schema…"
for f in sql/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=0 -q -f "$f" 2>&1 | grep -vi 'already exists' || true
done

rows=$(psql "$DATABASE_URL" -tAc "select count(*) from section" 2>/dev/null || echo 0)
if [ "${rows:-0}" -lt 1000 ]; then
  echo "restoring corpus (${rows} sections present)…"
  gunzip -c data/corpus.sql.gz | psql "$DATABASE_URL" -q
  echo "restored: $(psql "$DATABASE_URL" -tAc 'select count(*) from section') sections"
else
  echo "corpus already present: ${rows} sections"
fi

exec uv run uvicorn rfc_rag.interfaces.api:app --host 0.0.0.0 --port "$PORT"
