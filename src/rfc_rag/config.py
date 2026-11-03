import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rfc:rfc@localhost:5433/rfc")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss-20b-MXFP4-Q8")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-small-en-v1.5-bf16")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))

OMLX_SETTINGS = Path.home() / ".omlx" / "settings.json"


def api_key() -> str:
    key = os.getenv("LLM_API_KEY")
    if key:
        return key
    if "127.0.0.1:8000" in LLM_BASE_URL and OMLX_SETTINGS.exists():
        return json.loads(OMLX_SETTINGS.read_text())["auth"]["api_key"]
    return ""
