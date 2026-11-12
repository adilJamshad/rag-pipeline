import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rfc:rfc@localhost:5433/rfc")
# Chat. Stateless, so it may fall back and may be tiered.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss-20b-MXFP4-Q8")
LLM_MODEL_HEAVY = os.getenv("LLM_MODEL_HEAVY", "") or None

# Embeddings. A coordinate system, not a service: it must match the vectors
# already in the database, so it never falls back and defaults to the chat
# settings only when not configured separately.
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "") or LLM_BASE_URL
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-small-en-v1.5-bf16")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))

# Some providers (Gemini) default to a different size and need it requested.
_dims = os.getenv("EMBED_DIMENSIONS", "").strip()
EMBED_DIMENSIONS = int(_dims) if _dims else None

LLM_BACKEND = os.getenv("LLM_BACKEND", "direct")
# Embeddings may use a different backend from chat; defaults to the chat one.
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "") or LLM_BACKEND
LLM_FALLBACKS = [b.strip() for b in os.getenv("LLM_FALLBACKS", "").split(",") if b.strip()]

OMLX_SETTINGS = Path.home() / ".omlx" / "settings.json"


def _omlx_key() -> str:
    if OMLX_SETTINGS.exists():
        return json.loads(OMLX_SETTINGS.read_text())["auth"]["api_key"]
    return ""


# Provider-specific keys, so a .env can hold several without renaming.
PROVIDER_KEYS = {
    "api.groq.com": "GROQ_API_KEY",
    "generativelanguage.googleapis.com": "GEMINI_API_KEY",
    "api.openai.com": "OPENAI_API_KEY",
}


def _provider_key(base_url: str) -> str:
    for host, var in PROVIDER_KEYS.items():
        if host in base_url:
            return os.getenv(var, "")
    return ""


def api_key() -> str:
    return (os.getenv("LLM_API_KEY")
            or _provider_key(LLM_BASE_URL)
            or (_omlx_key() if "127.0.0.1:8000" in LLM_BASE_URL else ""))


def embed_api_key() -> str:
    key = os.getenv("EMBED_API_KEY")
    if key:
        return key
    if "127.0.0.1:8000" in EMBED_BASE_URL:
        return _omlx_key()
    return api_key() if EMBED_BASE_URL == LLM_BASE_URL else ""
